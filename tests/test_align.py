from conftest import two_speaker_dialogue

from daylog.align import align


def test_groups_words_per_speaker_and_drops_hallucinations():
    words, dia = two_speaker_dialogue()
    utts = align(words, dia.turns)
    assert [(u.speaker, u.text) for u in utts] == [
        ("SPEAKER_00", "Hoi Car, mail naar jan@example.com"),
        ("SPEAKER_01", "Prima, doe ik."),
    ]
    assert utts[0].start == 0.0
    assert utts[1].end == 3.9


def test_no_turns_means_no_utterances():
    words, _ = two_speaker_dialogue()
    assert align(words, []) == []
