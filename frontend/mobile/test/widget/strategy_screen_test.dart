/// Widget tests for StrategyScreen — proposals list, batch actions, status badges.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ai_trader_mobile/data/models/proposal.dart';
import 'package:ai_trader_mobile/providers/strategy_providers.dart';
import 'package:ai_trader_mobile/features/strategy/strategy_screen.dart';

void main() {
  Widget _wrap(List<Override> overrides) {
    return ProviderScope(
      overrides: overrides,
      child: const MaterialApp(home: StrategyScreen()),
    );
  }

  testWidgets('shows empty state when no proposals', (tester) async {
    await tester.pumpWidget(_wrap([
      proposalsProvider.overrideWith((_) async => <Proposal>[]),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('目前無提案'), findsOneWidget);
  });

  testWidgets('renders proposal with target_rule and status badge', (tester) async {
    final p = Proposal.fromJson({
      'proposal_id': 'abc12345-def',
      'target_rule': 'POSITION_REBALANCE',
      'status': 'pending',
      'confidence': 0.85,
      'proposed_value': 'reduce 2330 by 20%',
    });
    await tester.pumpWidget(_wrap([
      proposalsProvider.overrideWith((_) async => [p]),
    ]));
    await tester.pumpAndSettle();
    expect(find.textContaining('POSITION_REBALANCE'), findsOneWidget);
    expect(find.text('pending'), findsOneWidget);
    expect(find.text('Approve'), findsOneWidget);
    expect(find.text('Reject'), findsOneWidget);
  });

  testWidgets('approved proposal hides action buttons', (tester) async {
    final p = Proposal.fromJson({
      'proposal_id': 'abc12345-def',
      'target_rule': 'STRATEGY_DIRECTION',
      'status': 'approved',
      'confidence': 0.70,
    });
    await tester.pumpWidget(_wrap([
      proposalsProvider.overrideWith((_) async => [p]),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('approved'), findsOneWidget);
    expect(find.text('Approve'), findsNothing);
    expect(find.text('Reject'), findsNothing);
  });

  testWidgets('pending proposal shows checkbox', (tester) async {
    final p = Proposal.fromJson({
      'proposal_id': 'abc12345-def',
      'target_rule': 'POSITION_REBALANCE',
      'status': 'pending',
    });
    await tester.pumpWidget(_wrap([
      proposalsProvider.overrideWith((_) async => [p]),
    ]));
    await tester.pumpAndSettle();
    expect(find.byType(Checkbox), findsOneWidget);
  });

  testWidgets('confidence percentage displays correctly', (tester) async {
    final p = Proposal.fromJson({
      'proposal_id': 'abc12345-def',
      'target_rule': 'STRATEGY_DIRECTION',
      'status': 'pending',
      'confidence': 0.72,
    });
    await tester.pumpWidget(_wrap([
      proposalsProvider.overrideWith((_) async => [p]),
    ]));
    await tester.pumpAndSettle();
    expect(find.text('信心度 72%'), findsOneWidget);
  });
}
