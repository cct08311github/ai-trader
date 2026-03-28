import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../data/models/position.dart';
import 'core_providers.dart';

final positionsProvider = FutureProvider.autoDispose<List<Position>>((ref) async {
  final api = ref.watch(portfolioApiProvider);
  return api.fetchPositions();
});

final kpisProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final api = ref.watch(portfolioApiProvider);
  return api.fetchKpis();
});
