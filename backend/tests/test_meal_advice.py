"""Meal advice: the facts and verdict the AI is given."""
from app.meal_advice import meal_facts


def item(name, kcal, protein=10):
    return {"name": name, "calories": kcal, "protein_g": protein, "carbs_g": 0, "fat_g": 0}


def facts(meal, eaten_before=0, goal=2000, goal_type="maintain", eaten=False):
    return meal_facts([item("rice", meal)], eaten, eaten_before, goal, goal_type)


def test_fits_well():
    f = facts(500, eaten_before=600)
    assert (f.meal_kcal, f.eaten_before, f.left_before, f.left_after, f.over_by) == (500, 600, 1400, 900, 0)
    assert f.verdict == "fits_well"


def test_uses_most_boundary():
    assert facts(800, eaten_before=1000).verdict == "fits_well"    # exactly 80% of 1000 left
    assert facts(801, eaten_before=1000).verdict == "uses_most"


def test_goes_over():
    f = facts(900, eaten_before=1500)
    assert (f.verdict, f.left_after, f.over_by) == ("goes_over", -400, 400)


def test_zero_left_after_is_not_over():
    f = facts(500, eaten_before=1500)
    assert f.left_after == 0 and f.verdict == "uses_most"


def test_already_over_before_meal():
    f = facts(300, eaten_before=2100)
    assert (f.left_before, f.verdict, f.over_by) == (-100, "goes_over", 400)


def test_defaults():
    f = meal_facts([item("rice", 400)], True, 0, None, None)
    assert (f.goal, f.goal_type, f.eaten) == (2000, "maintain", True)


def test_zero_kcal_meal():
    f = meal_facts([item("tea", 0, protein=0)], False, 500, 2000, "lose")
    assert (f.meal_kcal, f.verdict, f.half_saves, f.biggest) == (0, "fits_well", 0, "tea")


def test_biggest_item_and_protein():
    f = meal_facts([item("dal", 150.4, 8.6), item("rice", 420.6, 7.2), item("roti", 420.6, 5)],
                   False, 0, 2000, "gain")
    assert (f.meal_kcal, f.biggest, f.half_saves, f.protein_g) == (992, "rice", 210, 21)


def test_rounding_of_eaten_before():
    assert facts(100, eaten_before=599.6).eaten_before == 600
