#!/usr/bin/env python3
"""
Nginx Log Monitor - Compact real-time dashboard for nginx log files
Auto-discovers log files from /etc/nginx/sites-enabled/
"""

import curses
import time
import re
import os
import glob
from collections import defaultdict, deque
from datetime import datetime
from threading import Thread, Lock
import signal
import sys

NGINX_SITES_DIR = "/etc/nginx/sites-enabled"
MAX_ERRORS = 5

# Regex patterns
ACCESS_LOG_PATTERN = re.compile(
    r'(?P<ip>\d+\.\d+\.\d+\.\d+).*?"(?P<method>\w+)\s+(?P<path>[^\s]+).*?"\s+(?P<status>\d+)\s+(?P<bytes>\d+)'
)
ERROR_LOG_PATTERN = re.compile(r'\[(?P<level>emerg|alert|crit|error|warn|notice|info|debug)\]')

# Config parsing patterns
ACCESS_LOG_CONF = re.compile(r'^\s*access_log\s+([^\s;]+)', re.MULTILINE)
ERROR_LOG_CONF = re.compile(r'^\s*error_log\s+([^\s;]+)', re.MULTILINE)
SERVER_NAME_CONF = re.compile(r'^\s*server_name\s+([^\s;]+)', re.MULTILINE)


def extract_server_name(domain):
    """Extract a meaningful short name from server_name directive"""
    if not domain:
        return None
    
    # Remove common prefixes
    name = domain.lower().replace('www.', '').replace('api.', '')
    
    # Split by dot and get parts
    parts = name.split('.')
    
    # Skip common TLDs and find first meaningful part
    tlds = {'com', 'org', 'net', 'io', 'ninja', 'co', 'app', 'dev', 'xyz', 'gg', 'uk', 'us', 'eu'}
    for part in parts:
        if part not in tlds and len(part) > 2:
            return part
    
    return parts[0] if parts else domain


def discover_log_files(sites_dir=NGINX_SITES_DIR):
    """Scan nginx config files and extract log paths with server names"""
    log_files = []
    seen = set()
    
    if not os.path.isdir(sites_dir):
        print(f"Warning: {sites_dir} not found", file=sys.stderr)
        return log_files
    
    conf_files = glob.glob(os.path.join(sites_dir, "*"))
    
    for conf_file in conf_files:
        if os.path.isfile(conf_file):
            try:
                with open(conf_file, 'r') as f:
                    content = f.read()
                
                # Try to find server_name for this config
                server_match = SERVER_NAME_CONF.search(content)
                raw_server = server_match.group(1) if server_match else os.path.basename(conf_file)
                server_name = extract_server_name(raw_server)
                
                # Find access logs
                for match in ACCESS_LOG_CONF.finditer(content):
                    path = match.group(1)
                    if path not in seen and path != 'off':
                        seen.add(path)
                        log_files.append({'path': path, 'server': server_name, 'type': 'access'})
                
                # Find error logs
                for match in ERROR_LOG_CONF.finditer(content):
                    path = match.group(1)
                    if path not in seen and path != 'off':
                        seen.add(path)
                        log_files.append({'path': path, 'server': server_name, 'type': 'error'})
                        
            except Exception as e:
                print(f"Warning: Could not read {conf_file}: {e}", file=sys.stderr)
    
    # Sort: access logs first, then error logs
    log_files.sort(key=lambda x: (1 if x['type'] == 'error' else 0, x['server']))
    
    return log_files


def format_bytes(bytes_val):
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}TB"


def format_rate(bytes_per_sec):
    """Format bytes/sec to human readable"""
    return format_bytes(bytes_per_sec) + "/s"


class LogStats:
    """Statistics container for a single log file"""
    def __init__(self, filepath, server_name=None):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.server_name = server_name or self.filename.replace('_access.log', '').replace('_error.log', '')
        self.is_error_log = 'error' in filepath.lower()
        self.lock = Lock()
        self.reset_interval_stats()
        self.reset_total_stats()
        self.file_exists = os.path.exists(filepath)
        
    def reset_interval_stats(self):
        with self.lock:
            self.interval_requests = 0
            self.interval_status_codes = defaultdict(int)
            self.interval_errors = 0
            self.interval_bytes = 0
            self.interval_ips = set()
    
    def reset_total_stats(self):
        with self.lock:
            self.total_requests = 0
            self.total_status_codes = defaultdict(int)
            self.total_errors = 0
            self.total_bytes = 0
            self.total_ips = set()
            self.recent_errors = deque(maxlen=MAX_ERRORS)
    
    def add_access_entry(self, status, bytes_sent, method, path, ip):
        with self.lock:
            self.interval_requests += 1
            self.total_requests += 1
            self.interval_status_codes[status] += 1
            self.total_status_codes[status] += 1
            self.interval_bytes += bytes_sent
            self.total_bytes += bytes_sent
            self.interval_ips.add(ip)
            self.total_ips.add(ip)
            if status >= 400:
                self.interval_errors += 1
                self.total_errors += 1
                ts = datetime.now().strftime("%H:%M:%S")
                self.recent_errors.append(f"{ts} {status} {method} {path[:80]}")
    
    def add_error_entry(self, level, message):
        with self.lock:
            self.interval_requests += 1
            self.total_requests += 1
            self.interval_errors += 1
            self.total_errors += 1
            ts = datetime.now().strftime("%H:%M:%S")
            self.recent_errors.append(f"{ts} [{level}] {message[:100]}")
    
    def get_stats(self):
        with self.lock:
            return {
                'int_req': self.interval_requests,
                'int_2xx': sum(v for k, v in self.interval_status_codes.items() if 200 <= k < 300),
                'int_4xx': sum(v for k, v in self.interval_status_codes.items() if 400 <= k < 500),
                'int_5xx': sum(v for k, v in self.interval_status_codes.items() if k >= 500),
                'int_err': self.interval_errors,
                'int_bytes': self.interval_bytes,
                'int_ips': len(self.interval_ips),
                'tot_req': self.total_requests,
                'tot_2xx': sum(v for k, v in self.total_status_codes.items() if 200 <= k < 300),
                'tot_4xx': sum(v for k, v in self.total_status_codes.items() if 400 <= k < 500),
                'tot_5xx': sum(v for k, v in self.total_status_codes.items() if k >= 500),
                'tot_err': self.total_errors,
                'tot_bytes': self.total_bytes,
                'tot_ips': len(self.total_ips),
                'recent_errors': list(self.recent_errors),
            }


class LogTailer(Thread):
    """Thread that tails a log file and updates stats"""
    def __init__(self, stats):
        super().__init__(daemon=True)
        self.stats = stats
        self.running = True
        
    def stop(self):
        self.running = False
        
    def run(self):
        while self.running:
            if not os.path.exists(self.stats.filepath):
                self.stats.file_exists = False
                time.sleep(1)
                continue
            
            self.stats.file_exists = True
            try:
                with open(self.stats.filepath, 'r') as f:
                    f.seek(0, 2)
                    while self.running:
                        line = f.readline()
                        if not line:
                            time.sleep(0.1)
                            try:
                                if os.stat(self.stats.filepath).st_ino != os.fstat(f.fileno()).st_ino:
                                    break
                            except:
                                break
                            continue
                        self.parse_line(line.strip())
            except:
                time.sleep(1)
    
    def parse_line(self, line):
        if self.stats.is_error_log:
            match = ERROR_LOG_PATTERN.search(line)
            if match:
                msg = line
                parts = line.split('] ')
                if len(parts) > 1:
                    msg = parts[-1]
                self.stats.add_error_entry(match.group('level'), msg[:200])
        else:
            match = ACCESS_LOG_PATTERN.search(line)
            if match:
                status = int(match.group('status'))
                bytes_sent = int(match.group('bytes'))
                method = match.group('method')
                path = match.group('path')
                ip = match.group('ip')
                self.stats.add_access_entry(status, bytes_sent, method, path, ip)


def draw_dashboard(stdscr, stats_list, refresh_interval):
    """Draw the compact monitoring dashboard"""
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(5, curses.COLOR_WHITE, -1)
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)
    
    GREEN = curses.color_pair(1)
    YELLOW = curses.color_pair(2)
    RED = curses.color_pair(3)
    CYAN = curses.color_pair(4)
    WHITE = curses.color_pair(5)
    MAGENTA = curses.color_pair(6)
    
    access_logs = [s for s in stats_list if not s.is_error_log]
    error_logs = [s for s in stats_list if s.is_error_log]
    
    # Find max server name length for column sizing
    max_name_len = max((len(s.server_name) for s in stats_list), default=10)
    max_name_len = min(max(max_name_len, 8), 20)  # Between 8 and 20 chars
    
    last_update = time.time()
    start_time = time.time()
    
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Calculate totals across all access logs
        total_int_req = 0
        total_int_bytes = 0
        total_int_2xx = 0
        total_int_4xx = 0
        total_int_5xx = 0
        total_int_ips = set()
        total_tot_req = 0
        total_tot_bytes = 0
        total_tot_ips = set()
        total_tot_err = 0
        
        for stats in access_logs:
            s = stats.get_stats()
            total_int_req += s['int_req']
            total_int_bytes += s['int_bytes']
            total_int_2xx += s['int_2xx']
            total_int_4xx += s['int_4xx']
            total_int_5xx += s['int_5xx']
            total_tot_req += s['tot_req']
            total_tot_bytes += s['tot_bytes']
            total_tot_err += s['tot_err']
            with stats.lock:
                total_int_ips.update(stats.interval_ips)
                total_tot_ips.update(stats.total_ips)
        
        for stats in error_logs:
            s = stats.get_stats()
            total_tot_err += s['tot_err']
        
        # Calculate rates
        elapsed = time.time() - start_time
        req_per_sec = total_tot_req / elapsed if elapsed > 0 else 0
        bytes_per_sec = total_int_bytes / refresh_interval if total_int_bytes > 0 else 0
        
        # Header
        timestamp = datetime.now().strftime("%H:%M:%S")
        header = f"NGINX MONITOR | {timestamp} | {refresh_interval}s refresh | q:quit r:reset"
        stdscr.addstr(0, 0, header[:width-1], CYAN | curses.A_BOLD)
        
        row = 2
        
        # Summary stats box
        stdscr.addstr(row, 0, "─" * min(width-1, 90), CYAN)
        row += 1
        
        # Line 1: Totals
        summary1 = f"Total: {total_tot_req:,} req | {format_bytes(total_tot_bytes)} | {len(total_tot_ips):,} unique IPs | {total_tot_err:,} errors"
        stdscr.addstr(row, 0, summary1[:width-1], WHITE | curses.A_BOLD)
        row += 1
        
        # Line 2: Rates
        summary2 = f"Rate:  {req_per_sec:.1f} req/s | {format_rate(bytes_per_sec)} | Interval: {total_int_req} req, {len(total_int_ips)} IPs"
        stdscr.addstr(row, 0, summary2[:width-1], WHITE)
        row += 1
        
        # Line 3: Status breakdown
        summary3 = f"Status: "
        stdscr.addstr(row, 0, summary3, WHITE)
        col = len(summary3)
        stdscr.addstr(row, col, f"2xx:{total_int_2xx:>5}", GREEN)
        col += 11
        stdscr.addstr(row, col, f"4xx:{total_int_4xx:>5}", YELLOW if total_int_4xx > 0 else WHITE)
        col += 11
        stdscr.addstr(row, col, f"5xx:{total_int_5xx:>5}", RED if total_int_5xx > 0 else WHITE)
        row += 1
        
        stdscr.addstr(row, 0, "─" * min(width-1, 90), CYAN)
        row += 1
        
        # Access logs section
        name_col = max_name_len + 2
        stdscr.addstr(row, 0, "ACCESS", WHITE | curses.A_BOLD)
        stdscr.addstr(row, name_col, "│ Interval", CYAN)
        stdscr.addstr(row, name_col + 26, "│ Total", CYAN)
        row += 1
        hdr = f"{'SERVER':<{max_name_len}}"
        stdscr.addstr(row, 0, hdr, WHITE)
        stdscr.addstr(row, name_col, "│ req   2xx   4xx   5xx", WHITE)
        stdscr.addstr(row, name_col + 26, "│ req      2xx     err", WHITE)
        row += 1
        
        for stats in access_logs:
            if row >= height - 10:
                break
            s = stats.get_stats()
            
            indicator = "●" if stats.file_exists else "○"
            color = GREEN if stats.file_exists else MAGENTA
            name_display = stats.server_name[:max_name_len]
            stdscr.addstr(row, 0, f"{indicator}{name_display:<{max_name_len}}", color)
            
            if stats.file_exists:
                stdscr.addstr(row, name_col, "│", CYAN)
                stdscr.addstr(row, name_col + 2, f"{s['int_req']:>4}", WHITE)
                stdscr.addstr(row, name_col + 7, f"{s['int_2xx']:>5}", GREEN)
                stdscr.addstr(row, name_col + 13, f"{s['int_4xx']:>5}", YELLOW if s['int_4xx'] > 0 else WHITE)
                stdscr.addstr(row, name_col + 19, f"{s['int_5xx']:>5}", RED if s['int_5xx'] > 0 else WHITE)
                
                stdscr.addstr(row, name_col + 26, "│", CYAN)
                stdscr.addstr(row, name_col + 28, f"{s['tot_req']:>6}", WHITE)
                stdscr.addstr(row, name_col + 35, f"{s['tot_2xx']:>8}", GREEN)
                stdscr.addstr(row, name_col + 44, f"{s['tot_err']:>7}", RED if s['tot_err'] > 0 else WHITE)
            row += 1
        
        row += 1
        
        # Error logs section
        stdscr.addstr(row, 0, "ERRORS", WHITE | curses.A_BOLD)
        stdscr.addstr(row, name_col, "│ int  total", CYAN)
        row += 1
        
        for stats in error_logs:
            if row >= height - 8:
                break
            s = stats.get_stats()
            
            indicator = "●" if stats.file_exists else "○"
            color = GREEN if stats.file_exists else MAGENTA
            name_display = stats.server_name[:max_name_len]
            stdscr.addstr(row, 0, f"{indicator}{name_display:<{max_name_len}}", color)
            
            if stats.file_exists:
                stdscr.addstr(row, name_col, "│", CYAN)
                err_color = RED if s['int_err'] > 0 else WHITE
                stdscr.addstr(row, name_col + 2, f"{s['int_err']:>4}", err_color)
                err_color = RED if s['tot_err'] > 0 else WHITE
                stdscr.addstr(row, name_col + 8, f"{s['tot_err']:>5}", err_color)
            row += 1
        
        row += 1
        
        # Collect all recent errors from all logs
        all_errors = []
        for stats in stats_list:
            s = stats.get_stats()
            for err in s['recent_errors']:
                all_errors.append((stats.server_name, stats.is_error_log, err))
        
        all_errors = all_errors[-MAX_ERRORS:]
        
        # Recent errors section
        stdscr.addstr(row, 0, "─" * min(width-1, 90), CYAN)
        row += 1
        stdscr.addstr(row, 0, f"RECENT ERRORS (last {MAX_ERRORS})", WHITE | curses.A_BOLD)
        row += 1
        
        if all_errors:
            for src, is_err, err in all_errors:
                if row >= height - 1:
                    break
                tag = "ERR" if is_err else "ACC"
                src_short = src[:8]
                prefix = f"{src_short:<8} {tag}"
                max_len = width - len(prefix) - 3
                err_display = err[:max_len] if len(err) > max_len else err
                stdscr.addstr(row, 0, prefix, YELLOW if is_err else MAGENTA)
                stdscr.addstr(row, len(prefix) + 1, err_display, RED)
                row += 1
        else:
            stdscr.addstr(row, 0, "  (none)", WHITE)
        
        stdscr.refresh()
        stdscr.timeout(100)
        
        current_time = time.time()
        while current_time - last_update < refresh_interval:
            try:
                key = stdscr.getch()
                if key == ord('q') or key == ord('Q'):
                    return
                elif key == ord('r') or key == ord('R'):
                    for stats in stats_list:
                        stats.reset_total_stats()
                        stats.reset_interval_stats()
                    start_time = time.time()
            except:
                pass
            time.sleep(0.1)
            current_time = time.time()
        
        for stats in stats_list:
            stats.reset_interval_stats()
        last_update = current_time


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Nginx Log Monitor - Auto-discovers logs from nginx config')
    parser.add_argument('-i', '--interval', type=int, default=10,
                        help='Refresh interval in seconds (default: 10)')
    parser.add_argument('-d', '--sites-dir', default=NGINX_SITES_DIR,
                        help=f'Nginx sites-enabled directory (default: {NGINX_SITES_DIR})')
    parser.add_argument('-f', '--files', nargs='+',
                        help='Manually specify log files (skips auto-discovery)')
    args = parser.parse_args()
    
    # Discover or use provided log files
    if args.files:
        log_entries = [{'path': f, 'server': None, 'type': 'error' if 'error' in f else 'access'} 
                       for f in args.files]
        print(f"Using {len(log_entries)} manually specified log file(s)")
    else:
        print(f"Scanning {args.sites_dir} for nginx configs...")
        log_entries = discover_log_files(args.sites_dir)
        
        if not log_entries:
            print("No log files found! Use -f to specify files manually.")
            print(f"Example: {sys.argv[0]} -f /var/log/nginx/access.log /var/log/nginx/error.log")
            sys.exit(1)
        
        print(f"Found {len(log_entries)} log file(s):")
        for entry in log_entries:
            print(f"  [{entry['server']}] {entry['path']}")
    
    time.sleep(1)  # Brief pause to show discovered files
    
    stats_list = [LogStats(entry['path'], entry['server']) for entry in log_entries]
    
    tailers = []
    for stats in stats_list:
        tailer = LogTailer(stats)
        tailer.start()
        tailers.append(tailer)
    
    def signal_handler(sig, frame):
        for tailer in tailers:
            tailer.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        curses.wrapper(lambda stdscr: draw_dashboard(stdscr, stats_list, args.interval))
    finally:
        for tailer in tailers:
            tailer.stop()


if __name__ == "__main__":
    main()
