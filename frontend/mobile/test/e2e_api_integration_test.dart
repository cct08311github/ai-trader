/// E2E integration tests — validates Flutter data layer against live backend.
///
/// Run: cd frontend/mobile && flutter test test/e2e_api_integration_test.dart
///
/// Requires: backend running at https://127.0.0.1:8080 with valid AUTH_TOKEN.
/// These tests are NOT meant for CI — they hit the real API.
///
/// Closes #501
library;

import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:dio/dio.dart';
import 'package:dio/io.dart';
import 'package:ai_trader_mobile/core/network/env.dart';
import 'package:ai_trader_mobile/core/network/log_store.dart';
import 'package:ai_trader_mobile/core/network/log_interceptor.dart';
import 'package:ai_trader_mobile/data/api/portfolio_api.dart';
import 'package:ai_trader_mobile/data/api/strategy_api.dart';
import 'package:ai_trader_mobile/data/api/control_api.dart';
import 'package:ai_trader_mobile/data/api/trades_api.dart';
import 'package:ai_trader_mobile/data/api/analysis_api.dart';
import 'package:ai_trader_mobile/data/models/position.dart';
import 'package:ai_trader_mobile/data/models/proposal.dart';
import 'package:ai_trader_mobile/data/models/control_status.dart';
import 'package:ai_trader_mobile/data/models/trade.dart';
import 'package:ai_trader_mobile/data/models/kline.dart';

/// Read AUTH_TOKEN from frontend/backend/.env (2 levels up from mobile/).
String _readToken() {
  final envFile = File('${Directory.current.path}/../backend/.env');
  if (!envFile.existsSync()) {
    throw StateError('Cannot find frontend/backend/.env — run from frontend/mobile/');
  }
  for (final line in envFile.readAsLinesSync()) {
    if (line.startsWith('AUTH_TOKEN')) {
      return line.split('=').skip(1).join('=').trim().replaceAll('"', '');
    }
  }
  throw StateError('AUTH_TOKEN not found in .env');
}

Dio _buildDio(String token, LogStore logStore) {
  final dio = Dio(BaseOptions(
    baseUrl: AppEnv.defaultBaseUrl,
    connectTimeout: AppEnv.connectTimeout,
    receiveTimeout: AppEnv.receiveTimeout,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $token',
    },
  ));
  // Trust self-signed cert for Tailscale
  final trustedHost = Uri.parse(AppEnv.defaultBaseUrl).host;
  (dio.httpClientAdapter as IOHttpClientAdapter).createHttpClient = () {
    final client = HttpClient();
    client.badCertificateCallback = (cert, host, port) => host == trustedHost;
    return client;
  };
  dio.interceptors.add(AppLogInterceptor(logStore));
  return dio;
}

void main() {
  late Dio dio;
  late LogStore logStore;
  late String token;

  setUpAll(() {
    token = _readToken();
    logStore = LogStore();
    dio = _buildDio(token, logStore);
  });

  // ── Portfolio Tab ──────────────────────────────────────────────────

  group('Portfolio API', () {
    late PortfolioApi api;
    setUp(() => api = PortfolioApi(dio));

    test('fetchPositions returns list of Position objects', () async {
      final positions = await api.fetchPositions();
      expect(positions, isA<List<Position>>());
      // At least verify the model parses without crash
      for (final p in positions) {
        expect(p.symbol, isNotEmpty);
        expect(p.qty, greaterThanOrEqualTo(0));
      }
    });

    test('fetchKpis returns map with expected keys', () async {
      final kpi = await api.fetchKpis();
      expect(kpi, contains('status'));
      // Should have data sub-key
      expect(kpi.containsKey('data') || kpi.containsKey('available_cash'), isTrue);
    });

    test('fetchQuote for 2330 returns valid response', () async {
      final quote = await api.fetchQuote('2330');
      expect(quote['status'], equals('ok'));
      expect(quote.containsKey('source'), isTrue);
    });

    test('fetchKline for 2330 returns candle data', () async {
      final bars = await api.fetchKline('2330', days: 5);
      expect(bars, isA<List>());
      if (bars.isNotEmpty) {
        final candle = KlineCandle.fromJson(bars.first);
        expect(candle.tradeDate, isNotEmpty);
        expect(candle.close, greaterThan(0));
      }
    });
  });

  // ── Strategy Tab ──────────────────────────────────────────────────

  group('Strategy API', () {
    late StrategyApi api;
    setUp(() => api = StrategyApi(dio));

    test('fetchProposals returns list of Proposal objects', () async {
      final proposals = await api.fetchProposals(limit: 5);
      expect(proposals, isA<List<Proposal>>());
      for (final p in proposals) {
        expect(p.proposalId, isNotEmpty);
        expect(p.status, isNotEmpty);
      }
    });

    test('fetchProposals with status filter works', () async {
      final pending = await api.fetchProposals(status: 'pending', limit: 5);
      for (final p in pending) {
        expect(p.status, equals('pending'));
      }
    });

    test('batchDecide with nonexistent ID returns failed', () async {
      final result = await api.batchDecide('approve', ['nonexistent-id-12345']);
      expect(result['status'], equals('ok'));
      expect((result['failed'] as List).length, equals(1));
      expect((result['succeeded'] as List), isEmpty);
    });

    test('approve with nonexistent ID returns error', () async {
      try {
        await api.approve('nonexistent-proposal-id');
        fail('Should have thrown');
      } on DioException catch (e) {
        // 404 or 500 expected
        expect(e.response?.statusCode, anyOf(404, 500));
      }
    });
  });

  // ── System Tab ────────────────────────────────────────────────────

  group('Control API', () {
    late ControlApi api;
    setUp(() => api = ControlApi(dio));

    test('fetchStatus returns valid ControlStatus', () async {
      final status = await api.fetchStatus();
      expect(status, isA<ControlStatus>());
      // simulation_mode should be true (known state from our system)
      expect(status.simulationMode, isTrue);
    });

    test('fetchStatus emergency_stop is bool', () async {
      final status = await api.fetchStatus();
      // Should not crash on bool parsing
      expect(status.emergencyStop, isA<bool>());
    });
  });

  // ── Trades Tab ────────────────────────────────────────────────────

  group('Trades API', () {
    late TradesApi api;
    setUp(() => api = TradesApi(dio));

    test('fetchTrades returns list of Trade objects', () async {
      final trades = await api.fetchTrades(limit: 5);
      expect(trades, isA<List<Trade>>());
      for (final t in trades) {
        expect(t.orderId, isNotEmpty);
        expect(t.symbol, isNotEmpty);
        expect(t.side.toLowerCase(), anyOf('buy', 'sell'));
      }
    });
  });

  // ── Analysis Tab ──────────────────────────────────────────────────

  group('Analysis API', () {
    late AnalysisApi api;
    setUp(() => api = AnalysisApi(dio));

    test('fetchLatest does not throw', () async {
      // May return empty data if no analysis exists — should not crash
      final result = await api.fetchLatest();
      expect(result, isA<Map<String, dynamic>>());
    });

    test('fetchReportContext returns map', () async {
      try {
        final result = await api.fetchReportContext('morning');
        expect(result, isA<Map<String, dynamic>>());
      } on DioException catch (e) {
        // 404 is acceptable if no report exists
        expect(e.response?.statusCode, equals(404));
      }
    });
  });

  // ── Error Handling ────────────────────────────────────────────────

  group('Error handling', () {
    test('wrong token returns 401', () async {
      final badDio = _buildDio('wrong-token', logStore);
      badDio.options.headers['Authorization'] = 'Bearer wrong-token';
      try {
        await badDio.get('/api/portfolio/positions');
        fail('Should have thrown');
      } on DioException catch (e) {
        expect(e.response?.statusCode, equals(401));
      }
    });

    test('nonexistent endpoint returns 404', () async {
      try {
        await dio.get('/api/nonexistent/endpoint');
        fail('Should have thrown');
      } on DioException catch (e) {
        expect(e.response?.statusCode, anyOf(404, 405));
      }
    });
  });

  // ── Log Store ─────────────────────────────────────────────────────

  group('LogStore integration', () {
    test('logs are recorded after API calls', () {
      // Previous API calls should have populated the log store
      expect(logStore.length, greaterThan(0));
      final lastEntry = logStore.entries.last;
      expect(lastEntry.method, isNotEmpty);
      expect(lastEntry.url, isNotEmpty);
    });

    test('log entries have valid structure', () {
      for (final entry in logStore.entries) {
        expect(entry.time, isA<DateTime>());
        expect(entry.durationMs, greaterThanOrEqualTo(0));
        expect(entry.level, anyOf('info', 'warn', 'error'));
        expect(entry.summary, isNotEmpty);
      }
    });
  });
}
