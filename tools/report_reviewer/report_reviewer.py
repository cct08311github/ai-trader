#!/usr/bin/env python3
"""Report Reviewer Agent for AI Trader.

Validates investment reports for:
1. Stock price accuracy (compare with real-time data)
2. Logical consistency (recommendations match data)
3. Source/time marking completeness

Usage:
    python3 report_reviewer.py --report-path <path/to/report.md>
    python3 report_reviewer.py --report-text "Report content here..."
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Add project scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

try:
    import yfinance as yf
except ImportError:
    print("Error: yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

_TZ_TWN = timezone(timedelta(hours=8))


class ReportReviewer:
    """Reviewer agent for investment reports."""
    
    PRICE_DEVIATION_WARNING = 15  # %
    PRICE_DEVIATION_ERROR = 30    # %
    
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.passed = True
        
    def extract_stock_symbols(self, text: str) -> list[str]:
        """Extract stock symbols from report text."""
        # Taiwan stocks: 4-6 digits followed by .TW or just 4-6 digits
        tw_pattern = r'\b(\d{4,6}(?:\.TW)?)\b'
        # US stocks: letters followed by $ or just uppercase letters
        us_pattern = r'\b([A-Z]{1,5}(?:\$)?)\b'
        
        tw_matches = re.findall(tw_pattern, text)
        us_matches = re.findall(us_pattern, text)
        
        # Filter common false positives
        false_positives = {'USD', 'TWD', 'API', 'AI', 'US', 'CEO', 'FDA', 'SEC', 'ETF', 'FII'}
        
        symbols = []
        for sym in tw_matches:
            if not sym.endswith('.TW'):
                sym = sym + '.TW'
            if sym not in symbols:
                symbols.append(sym)
        
        for sym in us_matches:
            if sym not in false_positives and sym not in symbols:
                symbols.append(sym)
        
        return symbols
    
    def extract_prices(self, text: str) -> dict:
        """Extract prices mentioned in report."""
        prices = {}
        
        # Pattern: stock symbol followed by price
        # e.g., "2330.TW 收盤價 1050" or "2330: 1050"
        patterns = [
            r'(\d{4,6}(?:\.TW)?)[:\s]+(?:收盤價|價格|股價|現價)?[:\s]*(\d+(?:\.\d+)?)',
            r'([A-Z]{1,5}(?:\$)?)[:\s]+(?:price|close)?[:\s]*(\d+(?:\.\d+)?)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for sym, price in matches:
                if not sym.endswith('.TW'):
                    sym = sym + '.TW' if sym.isdigit() else sym
                prices[sym] = float(price)
        
        return prices
    
    def fetch_realtime_price(self, symbol: str) -> Optional[dict]:
        """Fetch real-time price for a symbol."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price = info.get('currentPrice') or info.get('regularMarketPrice')
            prev_close = info.get('previousClose') or info.get('regularMarketPreviousClose')
            
            if price is None:
                return None
            
            return {
                'price': round(price, 2),
                'previous_close': round(prev_close, 2) if prev_close else None,
                'change': round(info.get('regularMarketChange', 0), 2),
                'percent_change': round(info.get('regularMarketChangePercent', 0), 2),
            }
        except Exception as e:
            return {'error': str(e)}
    
    def validate_price(self, symbol: str, reported_price: float, realtime_data: dict) -> dict:
        """Validate a single price against real-time data."""
        if 'error' in realtime_data:
            return {'status': 'error', 'message': realtime_data['error']}
        
        realtime_price = realtime_data.get('price')
        if realtime_price is None:
            return {'status': 'error', 'message': 'No price available'}
        
        deviation = ((reported_price - realtime_price) / realtime_price) * 100
        
        if abs(deviation) >= self.PRICE_DEVIATION_ERROR:
            status = 'error'
            message = f'偏離 {deviation:+.1f}% (>30%)'
        elif abs(deviation) >= self.PRICE_DEVIATION_WARNING:
            status = 'warning'
            message = f'偏離 {deviation:+.1f}% (>15%)'
        else:
            status = 'pass'
            message = f'偏離 {deviation:+.1f}%'
        
        return {
            'status': status,
            'reported': reported_price,
            'realtime': realtime_price,
            'deviation': deviation,
            'message': message,
        }
    
    def check_logical_consistency(self, text: str, prices: dict) -> list[dict]:
        """Check if recommendations are logically consistent with data."""
        issues = []
        
        # Check for "will limit up" but price change < 9%
        limit_up_pattern = r'(?:漲停|limit.?up|會漲).*?(\d+(?:\.\d+)?)%?'
        limit_down_pattern = r'(?:跌停|limit.?down|會跌).*?(\d+(?:\.\d+)?)%?'
        
        # Get actual percent changes
        for sym, price in prices.items():
            rt = self.fetch_realtime_price(sym)
            if rt and 'percent_change' in rt:
                pct = rt['percent_change']
                
                # Check limit up claim
                if pct < 9 and re.search(r'漲停', text):
                    issues.append({
                        'type': 'logical',
                        'severity': 'error',
                        'message': f'{sym} 漲幅僅 {pct:.1f}%，未達漲停'
                    })
                
                # Check limit down claim
                if pct > -9 and re.search(r'跌停', text):
                    issues.append({
                        'type': 'logical',
                        'severity': 'error',
                        'message': f'{sym} 跌幅僅 {pct:.1f}%，未達跌停'
                    })
        
        # Check RSI overbought but recommend buy
        rsi_buy_pattern = r'RSI[=:]?\s*([7-9]\d|100?).*?(?:買入|buy)'
        rsi_match = re.search(rsi_buy_pattern, text, re.IGNORECASE)
        if rsi_match:
            rsi = int(rsi_match.group(1))
            if rsi > 80:
                issues.append({
                    'type': 'logical',
                    'severity': 'warning',
                    'message': f'RSI={rsi} 過熱，但仍建議買入'
                })
        
        return issues
    
    def check_source_marking(self, text: str) -> list[dict]:
        """Check if report has proper source and time marking."""
        issues = []
        
        # Check for timestamps
        timestamp_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{4}/\d{2}/\d{2}',  # YYYY/MM/DD
            r'\d{1,2}:\d{2}',       # HH:MM
        ]
        
        has_timestamp = any(re.search(p, text) for p in timestamp_patterns)
        
        # Check for source keywords
        source_keywords = ['來源', 'source', '資料來源', 'data source', '截至', 'as of']
        has_source = any(kw in text.lower() for kw in source_keywords)
        
        if not has_timestamp:
            issues.append({
                'type': 'source',
                'severity': 'warning',
                'message': '報告缺少時間標記'
            })
        
        if not has_source:
            issues.append({
                'type': 'source',
                'severity': 'warning',
                'message': '報告缺少資料來源標記'
            })
        
        return issues
    
    def review(self, report_text: str) -> dict:
        """Main review function."""
        timestamp = datetime.now(_TZ_TWN).strftime('%Y-%m-%d %H:%M UTC+8')
        
        # Step 1: Extract symbols and prices
        symbols = self.extract_stock_symbols(report_text)
        prices = self.extract_prices(report_text)
        
        # Step 2: Validate prices
        price_results = {}
        for sym, price in prices.items():
            rt = self.fetch_realtime_price(sym)
            if rt:
                price_results[sym] = self.validate_price(sym, price, rt)
                
                if price_results[sym]['status'] == 'error':
                    self.issues.append(price_results[sym]['message'])
                    self.passed = False
                elif price_results[sym]['status'] == 'warning':
                    self.warnings.append(price_results[sym]['message'])
        
        # Step 3: Logical consistency
        logical_issues = self.check_logical_consistency(report_text, prices)
        for issue in logical_issues:
            if issue['severity'] == 'error':
                self.issues.append(issue['message'])
                self.passed = False
            else:
                self.warnings.append(issue['message'])
        
        # Step 4: Source marking
        source_issues = self.check_source_marking(report_text)
        for issue in source_issues:
            self.warnings.append(issue['message'])
        
        # Determine overall status
        if self.issues:
            status = '❌ 不通過'
        elif self.warnings:
            status = '⚠️ 警告'
        else:
            status = '✅ 通過'
        
        return {
            'status': status,
            'timestamp': timestamp,
            'symbols_found': symbols,
            'prices_validated': price_results,
            'issues': self.issues,
            'warnings': self.warnings,
            'passed': self.passed,
        }
    
    def format_report(self, result: dict) -> str:
        """Format review result as markdown report."""
        lines = [
            "# 報告審查結果",
            "",
            f"## 審查時間",
            result['timestamp'],
            "",
            f"## 審查摘要",
            f"- 狀態：{result['status']}",
            f"- 發現標的：{len(result['symbols_found'])} 個",
            f"- 已驗證價格：{len(result['prices_validated'])} 個",
            "",
        ]
        
        if result['prices_validated']:
            lines.append("## 股價驗證")
            lines.append("| 股票代碼 | 報告股價 | 即時股價 | 偏差 | 狀態 |")
            lines.append("|---------|---------|---------|------|------|")
            
            for sym, data in result['prices_validated'].items():
                status_icon = '✅' if data['status'] == 'pass' else ('⚠️' if data['status'] == 'warning' else '❌')
                if 'reported' not in data:
                    lines.append(f"| {sym} | - | - | - | {status_icon} {data.get('message', '')} |")
                else:
                    lines.append(
                        f"| {sym} | {data['reported']} | {data['realtime']} | {data['deviation']:+.1f}% | {status_icon} |"
                    )
            lines.append("")
        
        if result['issues']:
            lines.append("## 嚴重問題")
            for issue in result['issues']:
                lines.append(f"- ❌ {issue}")
            lines.append("")
        
        if result['warnings']:
            lines.append("## 警告")
            for warning in result['warnings']:
                lines.append(f"- ⚠️ {warning}")
            lines.append("")
        
        if not result['issues'] and not result['warnings']:
            lines.append("## 詳細問題")
            lines.append("（無）")
            lines.append("")
        
        # Recommendations
        lines.append("## 建議")
        if result['status'] == '❌ 不通過':
            lines.append("請修正上述問題後重新生成報告")
        elif result['status'] == '⚠️ 警告':
            lines.append("建議檢查警告項目，但報告仍可發布")
        else:
            lines.append("報告通過審查，可直接發布")
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Report Reviewer Agent')
    parser.add_argument('--report-path', type=str, help='Path to report file')
    parser.add_argument('--report-text', type=str, help='Report content as text')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    
    if args.report_path:
        with open(args.report_path, 'r', encoding='utf-8') as f:
            report_text = f.read()
    elif args.report_text:
        report_text = args.report_text
    else:
        print("Error: Must provide --report-path or --report-text")
        sys.exit(1)
    
    reviewer = ReportReviewer()
    result = reviewer.review(report_text)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(reviewer.format_report(result))
    
    # Exit code based on status
    sys.exit(0 if result['passed'] else 1)


if __name__ == "__main__":
    main()
