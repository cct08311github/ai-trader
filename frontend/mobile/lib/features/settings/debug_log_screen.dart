import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/core_providers.dart';

class DebugLogScreen extends ConsumerStatefulWidget {
  const DebugLogScreen({super.key});

  @override
  ConsumerState<DebugLogScreen> createState() => _DebugLogScreenState();
}

class _DebugLogScreenState extends ConsumerState<DebugLogScreen> {
  final _scrollController = ScrollController();
  final _searchController = TextEditingController();
  String _filter = '';

  @override
  void dispose() {
    _scrollController.dispose();
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final store = ref.watch(logStoreProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: const Text('Debug Logs'),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline, size: 20),
            tooltip: '清除',
            onPressed: () {
              store.clear();
              setState(() {});
            },
          ),
          IconButton(
            icon: const Icon(Icons.arrow_downward, size: 20),
            tooltip: '捲到底部',
            onPressed: () {
              if (_scrollController.hasClients) {
                _scrollController.animateTo(
                  _scrollController.position.maxScrollExtent,
                  duration: const Duration(milliseconds: 300),
                  curve: Curves.easeOut,
                );
              }
            },
          ),
        ],
      ),
      body: Column(
        children: [
          // Search bar
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: TextField(
              controller: _searchController,
              style: const TextStyle(color: Colors.white, fontSize: 13),
              decoration: InputDecoration(
                hintText: '搜尋 log...',
                hintStyle: const TextStyle(color: Colors.white24, fontSize: 13),
                prefixIcon: const Icon(Icons.search, color: Colors.white24, size: 18),
                filled: true,
                fillColor: const Color(0xFF1E293B),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(10),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 10),
              ),
              onChanged: (v) => setState(() => _filter = v.toLowerCase()),
            ),
          ),
          // Count
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(
              children: [
                Text(
                  '${store.length} 條 log',
                  style: const TextStyle(fontSize: 11, color: Colors.white38),
                ),
                const Spacer(),
                Text(
                  'max ${store.length}/${200}',
                  style: const TextStyle(fontSize: 11, color: Colors.white24),
                ),
              ],
            ),
          ),
          const SizedBox(height: 4),
          // Log list
          Expanded(
            child: ListenableBuilder(
              listenable: store,
              builder: (_, snapshot) {
                final entries = _filter.isEmpty
                    ? store.entries
                    : store.entries.where((e) => e.summary.toLowerCase().contains(_filter)).toList();
                if (entries.isEmpty) {
                  return const Center(
                    child: Text('無 log 記錄', style: TextStyle(color: Colors.white38)),
                  );
                }
                return ListView.builder(
                  controller: _scrollController,
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  itemCount: entries.length,
                  itemBuilder: (_, i) {
                    final e = entries[i];
                    final color = switch (e.level) {
                      'error' => Colors.redAccent,
                      'warn' => Colors.amber,
                      _ => Colors.white54,
                    };
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Text(
                        '${e.time.hour.toString().padLeft(2, '0')}:${e.time.minute.toString().padLeft(2, '0')}:${e.time.second.toString().padLeft(2, '0')} ${e.summary}',
                        style: TextStyle(
                          fontSize: 11,
                          fontFamily: 'monospace',
                          color: color,
                          height: 1.4,
                        ),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
