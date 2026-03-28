import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../../data/models/position.dart';
import '../../../data/models/kline.dart';
import '../../../providers/core_providers.dart';
import 'kline_chart.dart';

final _twdFmt = NumberFormat('#,##0', 'zh_TW');

/// Bottom sheet showing position detail + quote + K-line chart.
class PositionDetailSheet extends ConsumerStatefulWidget {
  final Position position;
  const PositionDetailSheet({super.key, required this.position});

  @override
  ConsumerState<PositionDetailSheet> createState() => _State();
}

class _State extends ConsumerState<PositionDetailSheet> {
  Map<String, dynamic>? _quote;
  List<KlineCandle>? _kline;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = ref.read(portfolioApiProvider);
    try {
      final results = await Future.wait([
        api.fetchQuote(widget.position.symbol),
        api.fetchKline(widget.position.symbol),
      ]);
      if (!mounted) return;
      setState(() {
        _quote = results[0] as Map<String, dynamic>;
        _kline = (results[1] as List)
            .map((j) => KlineCandle.fromJson(j as Map<String, dynamic>))
            .toList();
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.position;
    final pnl = p.unrealizedPnl ?? 0;
    final pnlColor = pnl >= 0 ? const Color(0xFF10B981) : Colors.redAccent;

    return DraggableScrollableSheet(
      initialChildSize: 0.75,
      maxChildSize: 0.95,
      minChildSize: 0.4,
      builder: (_, ctrl) => Container(
        decoration: const BoxDecoration(
          color: Color(0xFF1E293B),
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        child: ListView(
          controller: ctrl,
          padding: const EdgeInsets.all(20),
          children: [
            // Handle bar
            Center(
              child: Container(
                width: 40,
                height: 4,
                margin: const EdgeInsets.only(bottom: 16),
                decoration: BoxDecoration(
                  color: Colors.white24,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            // Symbol header
            Row(
              children: [
                Text(p.symbol,
                    style: const TextStyle(
                        fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white)),
                if (p.name != null) ...[
                  const SizedBox(width: 8),
                  Text(p.name!, style: const TextStyle(fontSize: 14, color: Colors.white54)),
                ],
              ],
            ),
            const SizedBox(height: 12),
            // Position summary row
            Row(
              children: [
                _InfoChip('持股', '${p.qty} 股'),
                _InfoChip('成本', p.avgPrice.toStringAsFixed(1)),
                _InfoChip('現價', p.lastPrice?.toStringAsFixed(1) ?? '-'),
                _InfoChip('損益', '${pnl >= 0 ? "+" : ""}${_twdFmt.format(pnl)}',
                    color: pnlColor),
              ],
            ),
            const SizedBox(height: 16),
            // Quote section
            if (_loading)
              const SizedBox(height: 60, child: Center(child: CircularProgressIndicator()))
            else if (_quote != null) ...[
              _QuoteRow(quote: _quote!),
              const SizedBox(height: 16),
            ],
            // K-line chart
            const Text('60 日 K 線',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: Colors.white70)),
            const SizedBox(height: 8),
            if (_loading)
              const SizedBox(height: 200, child: Center(child: CircularProgressIndicator()))
            else
              KlineChart(candles: _kline ?? []),
          ],
        ),
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  final String label;
  final String value;
  final Color? color;
  const _InfoChip(this.label, this.value, {this.color});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        children: [
          Text(label, style: const TextStyle(fontSize: 10, color: Colors.white38)),
          const SizedBox(height: 2),
          Text(value,
              style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: color ?? Colors.white)),
        ],
      ),
    );
  }
}

class _QuoteRow extends StatelessWidget {
  final Map<String, dynamic> quote;
  const _QuoteRow({required this.quote});

  @override
  Widget build(BuildContext context) {
    final data = quote['data'] as Map<String, dynamic>?;
    if (data == null) {
      return const Text('報價不可用', style: TextStyle(color: Colors.white38, fontSize: 12));
    }
    final change = (data['change_price'] ?? 0).toDouble();
    final rate = (data['change_rate'] ?? 0).toDouble();
    final color = change >= 0 ? const Color(0xFF10B981) : Colors.redAccent;
    final source = quote['source'] ?? '';

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF0F172A),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${(data['close'] ?? 0).toDouble().toStringAsFixed(1)}',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: color)),
              Text(
                '${change >= 0 ? "+" : ""}${change.toStringAsFixed(1)} (${rate >= 0 ? "+" : ""}${rate.toStringAsFixed(2)}%)',
                style: TextStyle(fontSize: 12, color: color),
              ),
            ],
          ),
          const Spacer(),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('量 ${_twdFmt.format(data['volume'] ?? 0)}',
                  style: const TextStyle(fontSize: 11, color: Colors.white38)),
              Text(source == 'eod' ? '收盤資料' : '即時',
                  style: const TextStyle(fontSize: 10, color: Colors.white24)),
            ],
          ),
        ],
      ),
    );
  }
}
