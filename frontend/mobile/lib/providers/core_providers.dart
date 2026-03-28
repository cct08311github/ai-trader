import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/storage/secure_storage.dart';
import '../core/network/dio_client.dart';
import '../data/api/portfolio_api.dart';
import '../data/api/strategy_api.dart';
import '../data/api/control_api.dart';

/// Secure storage singleton.
final storageProvider = Provider((_) => SecureStorage());

/// Dio HTTP client with auth interceptor.
final dioProvider = Provider((ref) {
  final storage = ref.watch(storageProvider);
  return createDio(storage);
});

/// API clients.
final portfolioApiProvider = Provider((ref) => PortfolioApi(ref.watch(dioProvider)));
final strategyApiProvider = Provider((ref) => StrategyApi(ref.watch(dioProvider)));
final controlApiProvider = Provider((ref) => ControlApi(ref.watch(dioProvider)));

/// Auth state — null means logged out.
final authTokenProvider = StateProvider<String?>((ref) => null);
