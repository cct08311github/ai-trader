import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'features/auth/login_screen.dart';
import 'features/portfolio/portfolio_screen.dart';
import 'features/strategy/strategy_screen.dart';
import 'features/system/system_screen.dart';
import 'features/trades/trades_screen.dart';
import 'features/analysis/analysis_screen.dart';
import 'features/settings/settings_screen.dart';
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
    WidgetsBinding.instance.addPostFrameCallback((_) => _checkAuth());
  }

  Future<void> _checkAuth() async {
    final storage = ref.read(storageProvider);
    final token = await storage.getToken();
    final savedUrl = await storage.getBaseUrl();
    if (savedUrl != null && savedUrl.isNotEmpty) {
      ref.read(baseUrlProvider.notifier).state = savedUrl;
    }
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
          ? _MainShell(onLogout: () => setState(() => _authenticated = false))
          : LoginScreen(
              onLoginSuccess: () => setState(() => _authenticated = true),
            ),
    );
  }
}

class _MainShell extends StatefulWidget {
  final VoidCallback onLogout;
  const _MainShell({required this.onLogout});

  @override
  State<_MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<_MainShell> {
  int _currentIndex = 0;

  late final List<Widget> _screens = [
    const PortfolioScreen(),
    const TradesScreen(),
    const StrategyScreen(),
    const SystemScreen(),
    const AnalysisScreen(),
    SettingsScreen(onLogout: widget.onLogout),
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
          NavigationDestination(icon: Icon(Icons.swap_horiz), label: '交易'),
          NavigationDestination(icon: Icon(Icons.psychology), label: '策略'),
          NavigationDestination(icon: Icon(Icons.monitor_heart), label: '系統'),
          NavigationDestination(icon: Icon(Icons.analytics), label: '分析'),
          NavigationDestination(icon: Icon(Icons.more_horiz), label: '更多'),
        ],
      ),
    );
  }
}
