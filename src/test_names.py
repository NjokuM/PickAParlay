from src.names import norm_name, same_player


def test_norm_name_strips_accents_punctuation_and_suffixes():
    assert norm_name("Nikola Jokić") == "nikola jokic"
    assert norm_name("C.J. McCollum") == "cj mccollum"
    assert norm_name("Derrick Jones Jr.") == "derrick jones"
    assert norm_name("Gary Payton II") == "gary payton"
    assert norm_name("De'Aaron Fox") == "deaaron fox"
    assert norm_name("Shai Gilgeous-Alexander") == "shai gilgeous alexander"


def test_norm_name_keeps_two_part_names_ending_in_suffix_like_tokens():
    # Only strips a suffix when a first and last name remain
    assert norm_name("Jr Smith") == "jr smith"
    assert norm_name("") == ""


def test_same_player_exact_and_short_first_names():
    assert same_player("Herb Jones", "Herbert Jones")
    assert same_player("Paul Reed Jr", "Paul Reed")
    assert same_player("Nikola Jokic", "Nikola Jokić")


def test_same_player_rejects_shared_surnames():
    # The bug that marked SGA "out" because Trey Alexander was
    assert not same_player("Shai Gilgeous-Alexander", "Trey Alexander")
    assert not same_player("Jalen Williams", "Jaylin Williams")
    assert not same_player("Al Horford", "Alan Horford Smith")
    assert not same_player("A Jones", "Al Jones")   # first names under 3 chars don't count
