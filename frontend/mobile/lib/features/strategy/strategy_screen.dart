import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/strategy_providers.dart';
import '../../providers/core_providers.dart';
import '../../data/models/proposal.dart';

class StrategyScreen extends ConsumerStatefulWidget {
  const StrategyScreen({super.key});

  @override
  ConsumerState<StrategyScreen> createState() => _StrategyScreenState();
}

class _StrategyScreenState extends ConsumerState<StrategyScreen> {
  final Set<String> _selected = {};
  bool _batchLoading = false;

  Future<void> _batchAction(String action) async {
    if (_selected.isEmpty) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E293B),
        title: Text(
          '批量${action == "approve" ? "核准" : "拒絕"} ${_selected.length} 筆提案',
          style: const TextStyle(color: Colors.white, fontSize: 16),
        ),
        content: const Text('此操作無法撤銷',
            style: TextStyle(color: Colors.white54, fontSize: 13)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('取消')),
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: action == 'approve'
                  ? const Color(0xFF10B981)
                  : Colors.redAccent,
            ),
            child: Text('確認${action == "approve" ? "核准" : "拒絕"}'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    setState(() => _batchLoading = true);
    try {
      final api = ref.read(strategyApiProvider);
      final result = await api.batchDecide(action, _selected.toList());
      final succeeded = (result['succeeded'] as List?)?.length ?? 0;
      final failed = (result['failed'] as List?)?.length ?? 0;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('$succeeded 筆已${action == "approve" ? "核准" : "拒絕"}'
              '${failed > 0 ? "，$failed 筆跳過" : ""}'),
          backgroundColor: const Color(0xFF10B981),
        ));
      }
      _selected.clear();
      ref.invalidate(proposalsProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('批量操作失敗: $e'), backgroundColor: Colors.redAccent));
      }
    } finally {
      setState(() => _batchLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(proposalsProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('策略提案'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: Column(
        children: [
          // Batch action bar
          if (_selected.isNotEmpty)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              color: const Color(0xFF1E293B),
              child: Row(
                children: [
                  Text('已選 ${_selected.length} 筆',
                      style: const TextStyle(color: Colors.white, fontSize: 13)),
                  const Spacer(),
                  _BatchBtn(
                      label: '批量核准',
                      color: const Color(0xFF10B981),
                      loading: _batchLoading,
                      onTap: () => _batchAction('approve')),
                  const SizedBox(width: 8),
                  _BatchBtn(
                      label: '批量拒絕',
                      color: Colors.redAccent,
                      loading: _batchLoading,
                      onTap: () => _batchAction('reject')),
                  const SizedBox(width: 8),
                  GestureDetector(
                    onTap: () => setState(() => _selected.clear()),
                    child: const Text('取消',
                        style: TextStyle(color: Colors.white38, fontSize: 12)),
                  ),
                ],
              ),
            ),
          // Proposal list
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async => ref.invalidate(proposalsProvider),
              child: async.when(
                data: (proposals) => proposals.isEmpty
                    ? const Center(
                        child: Text('目前無提案',
                            style: TextStyle(color: Colors.white54)))
                    : ListView.builder(
                        padding: const EdgeInsets.all(16),
                        itemCount: proposals.length,
                        itemBuilder: (_, i) => _ProposalTile(
                          proposal: proposals[i],
                          selected: _selected.contains(proposals[i].proposalId),
                          onSelect: (id, val) => setState(() {
                            val ? _selected.add(id) : _selected.remove(id);
                          }),
                          onApprove: () async {
                            final api = ref.read(strategyApiProvider);
                            await api.approve(proposals[i].proposalId);
                            ref.invalidate(proposalsProvider);
                          },
                          onReject: () async {
                            final api = ref.read(strategyApiProvider);
                            await api.reject(proposals[i].proposalId);
                            ref.invalidate(proposalsProvider);
                          },
                        ),
                      ),
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => Center(
                    child: Text('載入失敗: $e',
                        style: const TextStyle(color: Colors.redAccent))),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _BatchBtn extends StatelessWidget {
  final String label;
  final Color color;
  final bool loading;
  final VoidCallback onTap;
  const _BatchBtn(
      {required this.label,
      required this.color,
      required this.loading,
      required this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 32,
      child: ElevatedButton(
        onPressed: loading ? null : onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: color,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        child: Text(label, style: const TextStyle(fontSize: 12)),
      ),
    );
  }
}

class _ProposalTile extends StatelessWidget {
  final Proposal proposal;
  final bool selected;
  final void Function(String id, bool val) onSelect;
  final VoidCallback onApprove;
  final VoidCallback onReject;
  const _ProposalTile({
    required this.proposal,
    required this.selected,
    required this.onSelect,
    required this.onApprove,
    required this.onReject,
  });

  @override
  Widget build(BuildContext context) {
    final isPending = proposal.isPending;
    final statusColor = switch (proposal.status) {
      'approved' => const Color(0xFF10B981),
      'rejected' => Colors.redAccent,
      _ => Colors.amber,
    };

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
            color: selected ? const Color(0xFF10B981) : const Color(0xFF334155)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (isPending)
                SizedBox(
                  width: 24,
                  child: Checkbox(
                    value: selected,
                    onChanged: (v) =>
                        onSelect(proposal.proposalId, v ?? false),
                    activeColor: const Color(0xFF10B981),
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              Expanded(
                child: Text(
                  '${proposal.targetRule ?? "unknown"} — ${proposal.proposalId.substring(0, 8)}',
                  style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Colors.white),
                ),
              ),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                    color: statusColor.withAlpha(30),
                    borderRadius: BorderRadius.circular(6)),
                child: Text(proposal.status,
                    style: TextStyle(fontSize: 11, color: statusColor)),
              ),
            ],
          ),
          if (proposal.proposedValue != null) ...[
            const SizedBox(height: 6),
            Text(
              proposal.proposedValue!,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12, color: Colors.white54),
            ),
          ],
          if (proposal.confidence != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '信心度 ${(proposal.confidence! * 100).toStringAsFixed(0)}%',
                style: const TextStyle(fontSize: 11, color: Colors.white38),
              ),
            ),
          if (isPending) ...[
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                SizedBox(
                  height: 30,
                  child: ElevatedButton(
                    onPressed: onApprove,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF10B981),
                      padding: const EdgeInsets.symmetric(horizontal: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                    child: const Text('Approve', style: TextStyle(fontSize: 11)),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  height: 30,
                  child: ElevatedButton(
                    onPressed: onReject,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.redAccent,
                      padding: const EdgeInsets.symmetric(horizontal: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                    child: const Text('Reject', style: TextStyle(fontSize: 11)),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
