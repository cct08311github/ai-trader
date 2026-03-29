import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../data/models/proposal.dart';
import 'core_providers.dart';

final proposalsProvider = FutureProvider.autoDispose<List<Proposal>>((ref) async {
  final api = ref.watch(strategyApiProvider);
  return api.fetchProposals();
});

final pendingProposalsProvider = FutureProvider.autoDispose<List<Proposal>>((ref) async {
  final api = ref.watch(strategyApiProvider);
  return api.fetchProposals(status: 'pending');
});
