import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import '../../../data/models/kline.dart';

/// Candlestick K-line chart using fl_chart.
class KlineChart extends StatelessWidget {
  final List<KlineCandle> candles;
  const KlineChart({super.key, required this.candles});

  @override
  Widget build(BuildContext context) {
    if (candles.isEmpty) {
      return const SizedBox(
        height: 200,
        child: Center(child: Text('無 K 線資料', style: TextStyle(color: Colors.white38))),
      );
    }

    final minLow = candles.map((c) => c.low).reduce((a, b) => a < b ? a : b);
    final maxHigh = candles.map((c) => c.high).reduce((a, b) => a > b ? a : b);
    final padding = (maxHigh - minLow) * 0.05;

    return SizedBox(
      height: 220,
      child: BarChart(
        BarChartData(
          barGroups: List.generate(candles.length, (i) {
            final c = candles[i];
            return BarChartGroupData(
              x: i,
              barRods: [
                // Wick (high-low)
                BarChartRodData(
                  fromY: c.low,
                  toY: c.high,
                  width: 1,
                  color: c.isUp ? const Color(0xFF10B981) : Colors.redAccent,
                ),
                // Body (open-close)
                BarChartRodData(
                  fromY: c.isUp ? c.open : c.close,
                  toY: c.isUp ? c.close : c.open,
                  width: candles.length > 90 ? 2 : (candles.length > 40 ? 4 : 6),
                  color: c.isUp
                      ? const Color(0xFF10B981)
                      : Colors.redAccent,
                  borderRadius: BorderRadius.zero,
                ),
              ],
            );
          }),
          titlesData: FlTitlesData(
            leftTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                reservedSize: 50,
                getTitlesWidget: (value, _) => Text(
                  value.toStringAsFixed(0),
                  style: const TextStyle(fontSize: 9, color: Colors.white38),
                ),
              ),
            ),
            bottomTitles: AxisTitles(
              sideTitles: SideTitles(
                showTitles: true,
                interval: (candles.length / 4).ceilToDouble(),
                getTitlesWidget: (value, _) {
                  final idx = value.toInt();
                  if (idx < 0 || idx >= candles.length) return const SizedBox.shrink();
                  final date = candles[idx].tradeDate;
                  return Text(
                    date.length >= 10 ? date.substring(5) : date,
                    style: const TextStyle(fontSize: 8, color: Colors.white38),
                  );
                },
              ),
            ),
            topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
            rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          ),
          gridData: FlGridData(
            show: true,
            drawVerticalLine: false,
            getDrawingHorizontalLine: (_) =>
                const FlLine(color: Color(0xFF334155), strokeWidth: 0.5),
          ),
          borderData: FlBorderData(show: false),
          minY: minLow - padding,
          maxY: maxHigh + padding,
          barTouchData: BarTouchData(
            touchTooltipData: BarTouchTooltipData(
              getTooltipItem: (group, _, rod, rodIdx) {
                if (group.x < 0 || group.x >= candles.length) return null;
                final c = candles[group.x];
                return BarTooltipItem(
                  '${c.tradeDate}\nO:${c.open} H:${c.high}\nL:${c.low} C:${c.close}',
                  const TextStyle(fontSize: 10, color: Colors.white),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}
