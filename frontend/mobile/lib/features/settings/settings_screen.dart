import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/core_providers.dart';

class SettingsScreen extends ConsumerWidget {
  final VoidCallback onLogout;
  const SettingsScreen({super.key, required this.onLogout});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('更多'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SettingsTile(
            icon: Icons.info_outline,
            label: 'AI Trader Mobile v1.0.0',
            subtitle: 'Flutter + Riverpod',
          ),
          const Divider(color: Color(0xFF334155), height: 32),
          _SettingsTile(
            icon: Icons.logout,
            label: '登出',
            subtitle: '清除 token 並返回登入頁',
            onTap: () async {
              final confirmed = await showDialog<bool>(
                context: context,
                builder: (ctx) => AlertDialog(
                  backgroundColor: const Color(0xFF1E293B),
                  title: const Text('確認登出？', style: TextStyle(color: Colors.white)),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(ctx, false),
                        child: const Text('取消')),
                    ElevatedButton(
                      onPressed: () => Navigator.pop(ctx, true),
                      style: ElevatedButton.styleFrom(backgroundColor: Colors.redAccent),
                      child: const Text('登出'),
                    ),
                  ],
                ),
              );
              if (confirmed == true) {
                final storage = ref.read(storageProvider);
                await storage.clearToken();
                ref.read(authTokenProvider.notifier).state = null;
                onLogout();
              }
            },
          ),
        ],
      ),
    );
  }
}

class _SettingsTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final String? subtitle;
  final VoidCallback? onTap;
  const _SettingsTile({required this.icon, required this.label, this.subtitle, this.onTap});

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon, color: Colors.white38),
      title: Text(label, style: const TextStyle(color: Colors.white, fontSize: 14)),
      subtitle: subtitle != null
          ? Text(subtitle!, style: const TextStyle(color: Colors.white38, fontSize: 12))
          : null,
      onTap: onTap,
      contentPadding: EdgeInsets.zero,
    );
  }
}
