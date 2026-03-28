import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import '../../data/api/trades_api.dart';
import '../../data/models/trade.dart';
import '../../providers/core_providers.dart';

final _twdFmt = NumberFormat('#,##0', 'zh_TW');

final tradesApiProvider = Provider((ref) => TradesApi(ref.watch(dioProvider)));

final tradesProvider = FutureProvider.autoDispose<List<Trade>>((ref) async {
  final api = ref.watch(tradesApiProvider);
  return api.fetchTrades(limit: 100);
});

class TradesScreen extends ConsumerWidget {
  const TradesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(tradesProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('交易紀錄'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(tradesProvider),
        child: async.when(
          data: (trades) => trades.isEmpty
              ? const Center(
                  child: Text('目前無交易紀錄',
                      style: TextStyle(color: Colors.white54)))
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: trades.length,
                  itemBuilder: (_, i) => _TradeTile(trade: trades[i]),
                ),
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(
              child: Text('載入失敗: $e',
                  style: const TextStyle(color: Colors.redAccent))),
        ),
      ),
    );
  }
}

class _TradeTile extends StatelessWidget {
  final Trade trade;
  const _TradeTile({required this.trade});

  @override
  Widget build(BuildContext context) {
    final sideColor = trade.isBuy ? const Color(0xFF10B981) : Colors.redAccent;
    final sideLabel = trade.isBuy ? 'BUY' : 'SELL';

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: sideColor.withAlpha(30),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(sideLabel,
                style: TextStyle(
                    fontSize: 11, fontWeight: FontWeight.w700, color: sideColor)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(trade.symbol,
                    style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: Colors.white)),
                Text(
                    '${trade.qty} 股 @ ${trade.price.toStringAsFixed(1)}',
                    style: const TextStyle(fontSize: 11, color: Colors.white38)),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text('NT\$ ${_twdFmt.format(trade.amount)}',
                  style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Colors.white)),
              if (trade.tsSubmit != null)
                Text(trade.tsSubmit!.substring(0, 10),
                    style: const TextStyle(fontSize: 10, color: Colors.white24)),
            ],
          ),
        ],
      ),
    );
  }
}
