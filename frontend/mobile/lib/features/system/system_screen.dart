import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../data/models/control_status.dart';
import '../../providers/core_providers.dart';

final controlStatusProvider =
    FutureProvider.autoDispose<ControlStatus>((ref) async {
  final api = ref.watch(controlApiProvider);
  return api.fetchStatus();
});

class SystemScreen extends ConsumerWidget {
  const SystemScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statusAsync = ref.watch(controlStatusProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('系統控制'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(controlStatusProvider),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            statusAsync.when(
              data: (status) => _ControlPanel(status: status),
              loading: () =>
                  const Center(child: CircularProgressIndicator()),
              error: (e, _) => Text('載入失敗: $e',
                  style: const TextStyle(color: Colors.redAccent)),
            ),
          ],
        ),
      ),
    );
  }
}

class _ControlPanel extends ConsumerWidget {
  final ControlStatus status;
  const _ControlPanel({required this.status});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      children: [
        // Emergency stop
        if (status.emergencyStop)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            margin: const EdgeInsets.only(bottom: 16),
            decoration: BoxDecoration(
              color: Colors.red.withAlpha(30),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.redAccent),
            ),
            child: Column(
              children: [
                const Icon(Icons.warning_amber, color: Colors.redAccent, size: 32),
                const SizedBox(height: 8),
                const Text('緊急停止已啟動',
                    style: TextStyle(
                        color: Colors.redAccent,
                        fontSize: 16,
                        fontWeight: FontWeight.bold)),
                if (status.emergencyReason != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(status.emergencyReason!,
                        style:
                            const TextStyle(color: Colors.white54, fontSize: 12)),
                  ),
              ],
            ),
          ),

        // Status cards
        _StatusCard(
          icon: Icons.power_settings_new,
          label: '自動交易',
          value: status.autoTradingEnabled ? '啟用' : '停用',
          valueColor: status.autoTradingEnabled
              ? const Color(0xFF10B981)
              : Colors.white38,
        ),
        _StatusCard(
          icon: Icons.science,
          label: '交易模式',
          value: status.simulationMode ? '模擬盤' : '實盤',
          valueColor:
              status.simulationMode ? Colors.amber : const Color(0xFF10B981),
        ),
        if (status.autoLockActive)
          _StatusCard(
            icon: Icons.lock,
            label: '自動鎖定',
            value: '已觸發',
            valueColor: Colors.redAccent,
          ),
        if (status.modeWarning.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(status.modeWarning,
                style: const TextStyle(color: Colors.amber, fontSize: 12)),
          ),

        const SizedBox(height: 24),

        // Emergency stop button
        if (!status.emergencyStop)
          SizedBox(
            width: double.infinity,
            height: 56,
            child: ElevatedButton.icon(
              onPressed: () => _confirmEmergencyStop(context, ref),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16)),
              ),
              icon: const Icon(Icons.stop_circle, size: 28),
              label: const Text('緊急停止',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            ),
          )
        else
          SizedBox(
            width: double.infinity,
            height: 48,
            child: ElevatedButton(
              onPressed: () => _confirmResume(context, ref),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF10B981),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
              ),
              child: const Text('恢復交易', style: TextStyle(fontSize: 16)),
            ),
          ),
      ],
    );
  }

  void _confirmEmergencyStop(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E293B),
        title: const Text('確認緊急停止？',
            style: TextStyle(color: Colors.redAccent)),
        content: const Text('將立即停止所有自動交易。',
            style: TextStyle(color: Colors.white54)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('取消')),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                final api = ref.read(controlApiProvider);
                await api.emergencyStop();
                ref.invalidate(controlStatusProvider);
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('緊急停止失敗: $e'), backgroundColor: Colors.redAccent));
                }
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('確認停止'),
          ),
        ],
      ),
    );
  }

  void _confirmResume(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E293B),
        title: const Text('確認恢復交易？',
            style: TextStyle(color: Color(0xFF10B981))),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('取消')),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                final api = ref.read(controlApiProvider);
                await api.resumeTrading();
                ref.invalidate(controlStatusProvider);
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('恢復交易失敗: $e'), backgroundColor: Colors.redAccent));
                }
              }
            },
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF10B981)),
            child: const Text('確認恢復'),
          ),
        ],
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color valueColor;
  const _StatusCard(
      {required this.icon,
      required this.label,
      required this.value,
      required this.valueColor});

  @override
  Widget build(BuildContext context) {
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
          Icon(icon, color: Colors.white38, size: 20),
          const SizedBox(width: 12),
          Text(label,
              style: const TextStyle(fontSize: 14, color: Colors.white)),
          const Spacer(),
          Text(value,
              style: TextStyle(
                  fontSize: 14, fontWeight: FontWeight.w600, color: valueColor)),
        ],
      ),
    );
  }
}
