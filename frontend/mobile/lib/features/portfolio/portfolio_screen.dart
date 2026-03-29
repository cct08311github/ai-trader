import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../providers/portfolio_providers.dart';
import '../../data/models/position.dart';
import 'widgets/position_detail_sheet.dart';

final _twdFmt = NumberFormat('#,##0', 'zh_TW');

class PortfolioScreen extends ConsumerWidget {
  const PortfolioScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final posAsync = ref.watch(positionsProvider);
    final kpiAsync = ref.watch(kpisProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('持倉總覽'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(positionsProvider);
          ref.invalidate(kpisProvider);
        },
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            // KPI summary cards
            kpiAsync.when(
              data: (kpi) => _KpiBar(kpi: kpi),
              loading: () => const SizedBox(
                  height: 80,
                  child: Center(child: CircularProgressIndicator())),
              error: (e, _) => Text('KPI 載入失敗: $e',
                  style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
            ),
            const SizedBox(height: 16),
            // Position list
            posAsync.when(
              data: (positions) => positions.isEmpty
                  ? const Center(
                      child: Padding(
                          padding: EdgeInsets.all(32),
                          child: Text('目前無持倉',
                              style: TextStyle(color: Colors.white54))))
                  : Column(
                      children: positions
                          .map((p) => GestureDetector(
                                onTap: () => showModalBottomSheet(
                                  context: context,
                                  isScrollControlled: true,
                                  backgroundColor: Colors.transparent,
                                  builder: (_) => PositionDetailSheet(position: p),
                                ),
                                child: _PositionCard(position: p),
                              ))
                          .toList(),
                    ),
              loading: () =>
                  const Center(child: CircularProgressIndicator()),
              error: (e, _) => Text('持倉載入失敗: $e',
                  style: const TextStyle(color: Colors.redAccent, fontSize: 12)),
            ),
          ],
        ),
      ),
    );
  }
}

class _KpiBar extends StatelessWidget {
  final Map<String, dynamic> kpi;
  const _KpiBar({required this.kpi});

  @override
  Widget build(BuildContext context) {
    final totalValue = (kpi['total_market_value'] ?? 0).toDouble();
    final unrealizedPnl = (kpi['unrealized_pnl'] ?? kpi['total_unrealized_pnl'] ?? 0).toDouble();
    final winRate = (kpi['win_rate'] ?? kpi['overall_win_rate'] ?? 0).toDouble();

    return Row(
      children: [
        _KpiCard(label: '總市值', value: 'NT\$ ${_twdFmt.format(totalValue)}'),
        const SizedBox(width: 8),
        _KpiCard(
          label: '未實現損益',
          value: '${unrealizedPnl >= 0 ? "+" : ""}${_twdFmt.format(unrealizedPnl)}',
          valueColor: unrealizedPnl >= 0 ? const Color(0xFF10B981) : Colors.redAccent,
        ),
        const SizedBox(width: 8),
        _KpiCard(label: '勝率', value: '${(winRate * 100).toStringAsFixed(1)}%'),
      ],
    );
  }
}

class _KpiCard extends StatelessWidget {
  final String label;
  final String value;
  final Color? valueColor;
  const _KpiCard({required this.label, required this.value, this.valueColor});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFF1E293B),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFF334155)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: const TextStyle(fontSize: 11, color: Colors.white38)),
            const SizedBox(height: 4),
            Text(value,
                style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: valueColor ?? Colors.white)),
          ],
        ),
      ),
    );
  }
}

class _PositionCard extends StatelessWidget {
  final Position position;
  const _PositionCard({required this.position});

  @override
  Widget build(BuildContext context) {
    final pnl = position.unrealizedPnl ?? 0;
    final pnlColor = pnl >= 0 ? const Color(0xFF10B981) : Colors.redAccent;

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(position.symbol,
                        style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: Colors.white)),
                    if (position.name != null) ...[
                      const SizedBox(width: 6),
                      Text(position.name!,
                          style: const TextStyle(
                              fontSize: 12, color: Colors.white54)),
                    ],
                    if (position.locked)
                      const Padding(
                        padding: EdgeInsets.only(left: 6),
                        child: Icon(Icons.lock, size: 14, color: Colors.amber),
                      ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                    '${position.qty} 股 @ ${position.avgPrice.toStringAsFixed(1)}',
                    style: const TextStyle(fontSize: 12, color: Colors.white38)),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                position.lastPrice?.toStringAsFixed(1) ?? '-',
                style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: Colors.white),
              ),
              const SizedBox(height: 2),
              Text(
                '${pnl >= 0 ? "+" : ""}${_twdFmt.format(pnl)}',
                style: TextStyle(
                    fontSize: 12, fontWeight: FontWeight.w500, color: pnlColor),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
