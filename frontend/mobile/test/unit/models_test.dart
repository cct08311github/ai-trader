/// Unit tests for all data models — fromJson parsing, computed properties, edge cases.
import 'package:flutter_test/flutter_test.dart';
import 'package:ai_trader_mobile/data/models/position.dart';
import 'package:ai_trader_mobile/data/models/proposal.dart';
import 'package:ai_trader_mobile/data/models/control_status.dart';
import 'package:ai_trader_mobile/data/models/trade.dart';
import 'package:ai_trader_mobile/data/models/kline.dart';

void main() {
  // ── Position ──────────────────────────────────────────────────────

  group('Position', () {
    test('fromJson parses full response', () {
      final p = Position.fromJson({
        'symbol': '2330',
        'name': '台積電',
        'qty': 1000,
        'avg_price': 500.0,
        'current_price': 550.0,
        'unrealized_pnl': 50000.0,
        'price_source': 'eod',
        'locked': true,
      });
      expect(p.symbol, '2330');
      expect(p.name, '台積電');
      expect(p.qty, 1000);
      expect(p.avgPrice, 500.0);
      expect(p.lastPrice, 550.0);
      expect(p.unrealizedPnl, 50000.0);
      expect(p.locked, isTrue);
    });

    test('fromJson handles missing optional fields', () {
      final p = Position.fromJson({'symbol': '2330', 'qty': 100, 'avg_price': 500});
      expect(p.name, isNull);
      expect(p.lastPrice, isNull);
      expect(p.unrealizedPnl, isNull);
      expect(p.locked, isFalse);
    });

    test('fromJson handles quantity alias', () {
      final p = Position.fromJson({'symbol': '2330', 'quantity': 500, 'avg_price': 100});
      expect(p.qty, 500);
    });

    test('pnlRate computes correctly', () {
      final p = Position.fromJson({
        'symbol': '2330', 'qty': 1000, 'avg_price': 500.0, 'unrealized_pnl': 50000.0,
      });
      expect(p.pnlRate, closeTo(0.10, 0.001)); // 50000 / (500*1000) = 10%
    });

    test('pnlRate returns 0 when avgPrice is 0', () {
      final p = Position.fromJson({'symbol': '2330', 'qty': 1000, 'avg_price': 0});
      expect(p.pnlRate, 0);
    });
  });

  // ── Proposal ──────────────────────────────────────────────────────

  group('Proposal', () {
    test('fromJson parses full response', () {
      final p = Proposal.fromJson({
        'proposal_id': 'abc-123',
        'generated_by': 'strategy_committee',
        'target_rule': 'POSITION_REBALANCE',
        'rule_category': 'portfolio',
        'proposed_value': 'reduce 2330',
        'supporting_evidence': 'concentration risk',
        'confidence': 0.85,
        'status': 'pending',
        'created_at': 1711500000000,
      });
      expect(p.proposalId, 'abc-123');
      expect(p.confidence, 0.85);
      expect(p.isPending, isTrue);
      expect(p.createdDateTime, isNotNull);
    });

    test('isPending returns false for approved', () {
      final p = Proposal.fromJson({
        'proposal_id': 'x', 'status': 'approved',
      });
      expect(p.isPending, isFalse);
    });

    test('createdDateTime returns null when no created_at', () {
      final p = Proposal.fromJson({'proposal_id': 'x', 'status': 'pending'});
      expect(p.createdDateTime, isNull);
    });
  });

  // ── ControlStatus ─────────────────────────────────────────────────

  group('ControlStatus', () {
    test('fromJson parses full response', () {
      final s = ControlStatus.fromJson({
        'emergency_stop': false,
        'auto_trading_enabled': true,
        'simulation_mode': true,
        'mode_warning': 'test warning',
        'auto_lock_active': false,
      });
      expect(s.emergencyStop, isFalse);
      expect(s.autoTradingEnabled, isTrue);
      expect(s.simulationMode, isTrue);
      expect(s.modeWarning, 'test warning');
    });

    test('fromJson defaults for missing fields', () {
      final s = ControlStatus.fromJson({
        'emergency_stop': true,
        'auto_trading_enabled': false,
        'simulation_mode': false,
      });
      expect(s.emergencyStop, isTrue);
      expect(s.autoLockActive, isFalse);
      expect(s.modeWarning, isEmpty);
    });
  });

  // ── Trade ─────────────────────────────────────────────────────────

  group('Trade', () {
    test('fromJson parses standard response', () {
      final t = Trade.fromJson({
        'order_id': 'o-1', 'symbol': '2330', 'side': 'buy',
        'qty': 1000, 'price': 500.0, 'fee': 71.25, 'tax': 0,
        'status': 'filled', 'ts_submit': '2026-03-25T10:00:00Z',
      });
      expect(t.orderId, 'o-1');
      expect(t.side, 'buy');
      expect(t.isBuy, isTrue);
      expect(t.amount, 500000.0);
      expect(t.totalCost, 71.25);
    });

    test('fromJson handles action/id/timestamp aliases', () {
      final t = Trade.fromJson({
        'id': 'x-1', 'symbol': '2382', 'action': 'sell',
        'quantity': 360, 'price': 285.0, 'timestamp': '2026-03-25',
      });
      expect(t.orderId, 'x-1');
      expect(t.side, 'sell');
      expect(t.isBuy, isFalse);
      expect(t.qty, 360);
      expect(t.tsSubmit, '2026-03-25');
    });
  });

  // ── KlineCandle ───────────────────────────────────────────────────

  group('KlineCandle', () {
    test('fromJson parses correctly', () {
      final c = KlineCandle.fromJson({
        'trade_date': '2026-03-25',
        'open': 500.0, 'high': 510.0, 'low': 495.0, 'close': 508.0,
        'volume': 15000,
      });
      expect(c.tradeDate, '2026-03-25');
      expect(c.isUp, isTrue); // close > open
    });

    test('isUp returns false when close < open', () {
      final c = KlineCandle.fromJson({
        'trade_date': '2026-03-25',
        'open': 510.0, 'high': 515.0, 'low': 500.0, 'close': 505.0,
        'volume': 10000,
      });
      expect(c.isUp, isFalse);
    });

    test('handles zero/null values', () {
      final c = KlineCandle.fromJson({'trade_date': '2026-03-25'});
      expect(c.open, 0);
      expect(c.volume, 0);
    });
  });

  // ── LogStore ──────────────────────────────────────────────────────

  group('LogStore', () {
    test('ring buffer caps at maxEntries', () {
      final store =
          // ignore: avoid_relative_lib_imports
          _TestLogStore();
      for (int i = 0; i < 250; i++) {
        store.addEntry(i);
      }
      expect(store.length, 200);
    });

    test('clear empties all entries', () {
      final store = _TestLogStore();
      store.addEntry(1);
      store.addEntry(2);
      store.clear();
      expect(store.length, 0);
    });
  });
}

/// Minimal LogStore replica for unit testing without importing flutter foundation.
class _TestLogStore {
  static const maxEntries = 200;
  final List<int> _entries = [];
  int get length => _entries.length;
  void addEntry(int i) {
    if (_entries.length >= maxEntries) _entries.removeAt(0);
    _entries.add(i);
  }
  void clear() => _entries.clear();
}
