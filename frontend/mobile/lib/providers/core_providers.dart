import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/storage/secure_storage.dart';
import '../core/network/dio_client.dart';
import '../core/network/env.dart';
import '../data/api/portfolio_api.dart';
import '../data/api/strategy_api.dart';
import '../data/api/control_api.dart';

/// Secure storage singleton.
final storageProvider = Provider((_) => SecureStorage());

/// Base URL — updated from SecureStorage on login/init.
final baseUrlProvider = StateProvider<String>((_) => AppEnv.defaultBaseUrl);

/// Dio HTTP client with auth interceptor + dynamic base URL.
final dioProvider = Provider((ref) {
  final storage = ref.watch(storageProvider);
  final baseUrl = ref.watch(baseUrlProvider);
  return createDio(storage, baseUrl: baseUrl);
});

/// API clients.
final portfolioApiProvider = Provider((ref) => PortfolioApi(ref.watch(dioProvider)));
final strategyApiProvider = Provider((ref) => StrategyApi(ref.watch(dioProvider)));
final controlApiProvider = Provider((ref) => ControlApi(ref.watch(dioProvider)));

/// Auth state — null means logged out.
final authTokenProvider = StateProvider<String?>((ref) => null);
