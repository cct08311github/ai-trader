/// Widget tests for SystemScreen — control panel, emergency stop, status display.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ai_trader_mobile/data/models/control_status.dart';
import 'package:ai_trader_mobile/features/system/system_screen.dart';

void main() {
  Widget _wrap(ControlStatus status) {
    return ProviderScope(
      overrides: [
        controlStatusProvider.overrideWith((_) async => status),
      ],
      child: const MaterialApp(home: SystemScreen()),
    );
  }

  testWidgets('shows normal state — trading enabled + simulation', (tester) async {
    await tester.pumpWidget(_wrap(ControlStatus(
      emergencyStop: false,
      autoTradingEnabled: true,
      simulationMode: true,
    )));
    await tester.pumpAndSettle();
    expect(find.text('啟用'), findsOneWidget);
    expect(find.text('模擬盤'), findsOneWidget);
    expect(find.text('緊急停止'), findsOneWidget);
  });

  testWidgets('shows emergency stop warning banner', (tester) async {
    await tester.pumpWidget(_wrap(ControlStatus(
      emergencyStop: true,
      emergencyReason: '手動觸發',
      autoTradingEnabled: false,
      simulationMode: true,
    )));
    await tester.pumpAndSettle();
    expect(find.text('緊急停止已啟動'), findsOneWidget);
    expect(find.text('手動觸發'), findsOneWidget);
    expect(find.text('恢復交易'), findsOneWidget);
    // Emergency stop button should NOT be shown when already stopped
    expect(find.text('緊急停止'), findsNothing);
  });

  testWidgets('auto-lock shows indicator', (tester) async {
    await tester.pumpWidget(_wrap(ControlStatus(
      emergencyStop: false,
      autoTradingEnabled: true,
      simulationMode: true,
      autoLockActive: true,
    )));
    await tester.pumpAndSettle();
    expect(find.text('已觸發'), findsOneWidget);
  });

  testWidgets('emergency stop button shows confirmation dialog', (tester) async {
    await tester.pumpWidget(_wrap(ControlStatus(
      emergencyStop: false,
      autoTradingEnabled: true,
      simulationMode: true,
    )));
    await tester.pumpAndSettle();
    await tester.tap(find.text('緊急停止'));
    await tester.pumpAndSettle();
    expect(find.text('確認緊急停止？'), findsOneWidget);
    expect(find.text('確認停止'), findsOneWidget);
    expect(find.text('取消'), findsOneWidget);
  });

  testWidgets('mode warning displays when present', (tester) async {
    await tester.pumpWidget(_wrap(ControlStatus(
      emergencyStop: false,
      autoTradingEnabled: true,
      simulationMode: false,
      modeWarning: '注意：實盤模式',
    )));
    await tester.pumpAndSettle();
    expect(find.text('注意：實盤模式'), findsOneWidget);
    expect(find.text('實盤'), findsOneWidget);
  });
}
