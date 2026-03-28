import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/api/analysis_api.dart';
import '../../providers/core_providers.dart';

final analysisApiProvider =
    Provider((ref) => AnalysisApi(ref.watch(dioProvider)));

final analysisProvider =
    FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final api = ref.watch(analysisApiProvider);
  return api.fetchLatest();
});

class AnalysisScreen extends ConsumerWidget {
  const AnalysisScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(analysisProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('盤後分析'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(analysisProvider),
        child: async.when(
          data: (data) {
            final report = data['data'] as Map<String, dynamic>?;
            if (report == null) {
              return const Center(
                  child: Text('無分析資料', style: TextStyle(color: Colors.white54)));
            }
            final tradeDate = report['trade_date'] ?? '-';
            final sections = <_Section>[];

            // Extract key sections from the report JSON
            for (final key in ['market_summary', 'technical', 'strategy', 'ai_insights']) {
              final val = report[key];
              if (val != null) {
                sections.add(_Section(
                  title: _sectionTitle(key),
                  content: val is String ? val : const JsonEncoder.withIndent('  ').convert(val),
                ));
              }
            }

            return ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text('交易日：$tradeDate',
                    style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: Colors.white)),
                const SizedBox(height: 16),
                ...sections.map((s) => _ReportSection(section: s)),
                if (sections.isEmpty)
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E293B),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      const JsonEncoder.withIndent('  ').convert(report),
                      style: const TextStyle(fontSize: 11, color: Colors.white54, fontFamily: 'monospace'),
                    ),
                  ),
              ],
            );
          },
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(
              child: Text('載入失敗: $e', style: const TextStyle(color: Colors.redAccent))),
        ),
      ),
    );
  }

  static String _sectionTitle(String key) => switch (key) {
        'market_summary' => '市場概覽',
        'technical' => '技術分析',
        'strategy' => 'AI 策略',
        'ai_insights' => 'AI 洞察',
        _ => key,
      };
}

class _Section {
  final String title;
  final String content;
  _Section({required this.title, required this.content});
}

class _ReportSection extends StatelessWidget {
  final _Section section;
  const _ReportSection({required this.section});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(section.title,
              style: const TextStyle(
                  fontSize: 14, fontWeight: FontWeight.w600, color: Colors.white)),
          const SizedBox(height: 8),
          Text(section.content,
              style: const TextStyle(fontSize: 12, color: Colors.white60, height: 1.5)),
        ],
      ),
    );
  }
}
