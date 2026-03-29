/// Widget tests for PortfolioScreen — rendering, KPI cards, position list.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ai_trader_mobile/data/models/position.dart';
import 'package:ai_trader_mobile/providers/portfolio_providers.dart';
import 'package:ai_trader_mobile/features/portfolio/portfolio_screen.dart';

void main() {
  Widget _wrap(List<Override> overrides) {
    return ProviderScope(
      overrides: overrides,
      child: const MaterialApp(home: PortfolioScreen()),
    );
  }

  testWidgets('shows AppBar title', (tester) async {
    await tester.pumpWidget(_wrap([
      positionsProvider.overrideWith((_) async => <Position>[]),
      kpisProvider.overrideWith((_) async => <String, dynamic>{
            'data': {'available_cash': 0, 'today_trades_count': 0, 'overall_win_rate': 0}
          }),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('持倉總覽'), findsOneWidget);
  });

  testWidgets('shows empty state when no positions', (tester) async {
    await tester.pumpWidget(_wrap([
      positionsProvider.overrideWith((_) async => <Position>[]),
      kpisProvider.overrideWith((_) async => <String, dynamic>{
            'data': {'available_cash': 0, 'today_trades_count': 0, 'overall_win_rate': 0}
          }),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('目前無持倉'), findsOneWidget);
  });

  testWidgets('renders position card with symbol', (tester) async {
    final pos = Position.fromJson({
      'symbol': '2330', 'name': '台積電', 'qty': 1000,
      'avg_price': 500.0, 'current_price': 550.0, 'unrealized_pnl': 50000.0,
    });
    await tester.pumpWidget(_wrap([
      positionsProvider.overrideWith((_) async => [pos]),
      kpisProvider.overrideWith((_) async => <String, dynamic>{
            'data': {'available_cash': 1000000, 'today_trades_count': 0, 'overall_win_rate': 0.8}
          }),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('2330'), findsOneWidget);
    expect(find.text('台積電'), findsOneWidget);
    expect(find.textContaining('+50,000'), findsOneWidget);
  });

  testWidgets('shows KPI cards with values', (tester) async {
    await tester.pumpWidget(_wrap([
      positionsProvider.overrideWith((_) async => <Position>[]),
      kpisProvider.overrideWith((_) async => <String, dynamic>{
            'data': {
              'available_cash': 500000,
              'total_market_value': 1500000,
              'total_unrealized_pnl': 25000,
              'overall_win_rate': 0.75,
            }
          }),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('總市值'), findsOneWidget);
    expect(find.text('未實現損益'), findsOneWidget);
    expect(find.text('勝率'), findsOneWidget);
  });

  testWidgets('shows error state on API failure', (tester) async {
    await tester.pumpWidget(_wrap([
      positionsProvider.overrideWith((_) => throw Exception('Network error')),
      kpisProvider.overrideWith((_) => throw Exception('Network error')),
    ]));
    await tester.pumpAndSettle();
    expect(find.textContaining('載入失敗'), findsWidgets);
  });
}
