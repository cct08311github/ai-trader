import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'features/auth/login_screen.dart';
import 'features/portfolio/portfolio_screen.dart';
import 'features/strategy/strategy_screen.dart';
import 'features/system/system_screen.dart';
import 'providers/core_providers.dart';

class AiTraderApp extends ConsumerStatefulWidget {
  const AiTraderApp({super.key});

  @override
  ConsumerState<AiTraderApp> createState() => _AiTraderAppState();
}

class _AiTraderAppState extends ConsumerState<AiTraderApp> {
  bool _authenticated = false;

  @override
  void initState() {
    super.initState();
    _checkAuth();
  }

  Future<void> _checkAuth() async {
    final storage = ref.read(storageProvider);
    final token = await storage.getToken();
    if (token != null && token.isNotEmpty) {
      ref.read(authTokenProvider.notifier).state = token;
      setState(() => _authenticated = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Trader',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF0F172A),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF10B981),
          surface: Color(0xFF1E293B),
        ),
      ),
      home: _authenticated
          ? const _MainShell()
          : LoginScreen(
              onLoginSuccess: () => setState(() => _authenticated = true),
            ),
    );
  }
}

class _MainShell extends StatefulWidget {
  const _MainShell();

  @override
  State<_MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<_MainShell> {
  int _currentIndex = 0;

  static const _screens = <Widget>[
    PortfolioScreen(),
    StrategyScreen(),
    SystemScreen(),
    // Placeholder for Analysis + More tabs (Phase 5-6)
    _PlaceholderTab(label: '盤後分析'),
    _PlaceholderTab(label: '更多'),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _currentIndex, children: _screens),
      bottomNavigationBar: NavigationBar(
        backgroundColor: const Color(0xFF1E293B),
        indicatorColor: const Color(0xFF10B981).withAlpha(40),
        selectedIndex: _currentIndex,
        onDestinationSelected: (i) => setState(() => _currentIndex = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.account_balance_wallet), label: '持倉'),
          NavigationDestination(icon: Icon(Icons.psychology), label: '策略'),
          NavigationDestination(icon: Icon(Icons.monitor_heart), label: '系統'),
          NavigationDestination(icon: Icon(Icons.analytics), label: '分析'),
          NavigationDestination(icon: Icon(Icons.more_horiz), label: '更多'),
        ],
      ),
    );
  }
}

class _PlaceholderTab extends StatelessWidget {
  final String label;
  const _PlaceholderTab({required this.label});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        title: Text(label),
        backgroundColor: const Color(0xFF0F172A),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: Center(
        child: Text('$label — 開發中',
            style: const TextStyle(color: Colors.white38)),
      ),
    );
  }
}
