from src.seeds import N_RUNS, SEEDS


def test_treinta_semillas_distintas():
    assert len(SEEDS) == N_RUNS == 30
    assert len(set(SEEDS)) == 30
