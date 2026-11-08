"""check_advice and fallback_text: nothing unsafe or wrong reaches the screen."""
from itertools import product

import pytest

from app.meal_advice import AdviceRejected, check_advice, fallback_text, meal_facts


def item(name, kcal):
    return {"name": name, "calories": kcal, "protein_g": 10, "carbs_g": 0, "fat_g": 0}


def F(meal=1050, before=600, goal=2000, goal_type="maintain", eaten=False, name="fried rice"):
    return meal_facts([item(name, meal)], eaten, before, goal, goal_type)


def reason(text, facts=None):
    with pytest.raises(AdviceRejected) as exc:
        check_advice(text, facts or F())
    return exc.value.reason


def test_good_text_passes_stripped():
    assert check_advice("  About 1,050 kcal, which leaves 350 kcal for today.  ", F()) == \
        "About 1,050 kcal, which leaves 350 kcal for today."


def test_rejects_empty():
    assert reason("   ") == "empty"


def test_rejects_too_long():
    assert reason("Nice meal. " * 40) == "too_long"


def test_rejects_link():
    for t in ("See http://x.io", "Visit www.food.org", "Try example.com"):
        assert reason(t) == "link"


def test_rejects_blocked():
    for t in ("Maybe don't eat this.", "Don’t eat the rice.", "Do not eat it all.", "Skip the rice tonight.",
              "Try skipping dinner.", "You're starving yourself.", "Try fasting tomorrow.", "A short fast helps.",
              "Go for a run to burn it off.", "No need to feel guilty.", "A cheat meal is fine.",
              "Don't punish yourself.", "Never purge.", "If you throw up, rest.", "Don't feel ashamed.",
              "No shame here.", "That is bad food."):
        assert reason(t) == "blocked", t


def test_breakfast_is_not_fast():
    assert check_advice("A filling breakfast at about 1,050 kcal.", F())


def test_number_formats():
    assert check_advice("This is 1,050 calories.", F())
    assert check_advice("This is 1050kcal.", F())
    assert reason("This is 1,200 kcal.") == "wrong_number"


def test_tolerance():
    f = F()                                        # meal 1050: ±31.5 allowed (3%)
    assert check_advice("About 1,080 kcal.", f)
    assert reason("About 1,090 kcal.", f) == "wrong_number"
    small = F(meal=100, before=0)                  # meal 100: ±10 allowed
    assert check_advice("About 110 kcal.", small)
    assert reason("About 125 kcal.", small) == "wrong_number"


def test_all_fact_numbers_allowed():
    f = F(meal=900, before=1500)                   # over by 400, left before 500, total 2400
    for n in (900, 1500, 2400, 2000, 500, 400, 450):
        assert check_advice(f"Mentions {n:,} kcal.", f), n


def test_numbers_without_unit_ignored():
    assert check_advice("Add 2 eggs for about 12 g protein.", F())


def test_every_fallback_passes_checks():
    cases = [dict(meal=m, before=b) for m, b in ((400, 300), (900, 1000), (900, 1500), (300, 2100), (0, 500))]
    for c, eaten, gt in product(cases, (False, True), ("lose", "maintain", "gain")):
        f = F(eaten=eaten, goal_type=gt, **c)
        assert check_advice(fallback_text(f), f) == fallback_text(f), (c, eaten, gt)


def test_fallback_copy():
    assert fallback_text(F(meal=900, before=1500)) == (
        "About 900 kcal, which would put today 400 kcal over your 2,000 kcal goal. "
        "A smaller portion of the fried rice saves about 450 kcal.")
    assert fallback_text(F(meal=900, before=1500, eaten=True)) == (
        "About 900 kcal, which puts today 400 kcal over your 2,000 kcal goal. "
        "One day over is fine; tomorrow is a fresh start.")
    assert fallback_text(F(meal=900, before=1500, goal_type="gain")) == (
        "About 900 kcal, which puts today 400 kcal above your 2,000 kcal goal. "
        "That's fine while you're building.")
    assert fallback_text(F(meal=400, before=300)) == (
        "About 400 kcal. That leaves 1,300 kcal of your 2,000 kcal goal today.")
    assert fallback_text(F(meal=900, before=1000)) == (
        "About 900 kcal, most of the 1,000 kcal you have left today. "
        "A smaller portion of the fried rice would leave more room for later.")
    assert fallback_text(F(meal=900, before=1000, eaten=True)) == (
        "About 900 kcal, most of the 1,000 kcal you had left today. "
        "A lighter next meal will keep you on track.")


def test_fallback_drops_a_name_that_trips_the_checks():
    for name in ("skipjack tuna fasting bowl", "250 kcal protein bar", "www.snack"):
        f = F(meal=900, before=1500, name=name)
        text = fallback_text(f)
        assert name not in text and check_advice(text, f) == text


def test_fits_well_rejects_restrictive_tips():
    f = F(meal=400, before=300)                                   # fits_well
    for t in ("You could have half of it.", "Try a smaller portion.", "Maybe cut back on the rice.",
              "Eat less of the fried rice.", "Save some for later."):
        assert reason(t, f) == "restrictive_tip", t
    assert check_advice("A good fit for today, with 10 g of protein.", f)


def test_portion_tips_allowed_when_it_uses_most_or_goes_over():
    assert check_advice("Half of the fried rice saves about 450 kcal.", F(meal=900, before=1500))
    assert check_advice("A smaller portion would leave room later.", F(meal=900, before=1000))


def test_large_meal_is_not_comfortable():
    f = F(meal=900, before=0)                                     # fits_well but 45% of the goal
    assert reason("This fits comfortably into your day.", f) == "too_comfortable"
    assert check_advice("This fits comfortably into your day.", F(meal=400, before=300))


# ---- review fixes ----

def test_wrong_direction_is_rejected():
    under = F(meal=1000, before=500)                              # 500 left after: not over
    assert reason("That's about 1,000 kcal, putting you 500 kcal over your goal.", under) == "wrong_direction"
    assert reason("This takes you past your 2,000 kcal goal.", under) == "wrong_direction"
    over = F(meal=400, before=1900)                               # 300 over
    assert reason("You have 300 kcal left today.", over) == "wrong_direction"
    assert check_advice("This puts today 300 kcal over your 2,000 kcal goal.", over)
    assert check_advice("Spread your meals over the day; 500 kcal left.", under)


def test_negative_left_is_not_an_allowed_number():
    over = F(meal=400, before=2300)                               # left before −300, left after −700
    assert reason("That leaves 300 kcal.", over) in ("wrong_number", "wrong_direction")


def test_more_number_forms_are_checked():
    f = F()                                                       # meal 1050
    for t in ("This is 1,200 kcals.", "A 1,800-calorie meal.", "A 1,800 calorie plate.", "About 9000 cal.",
              "About 3,000 kilocalories.", "About 2.5k kcal.", "About 1000.4 kcal.", "About 1,200 Cal."):
        assert reason(t, f) == "wrong_number", t
    for t in ("About 1,050 kcals.", "A 1,050-calorie meal.", "About 1.05k kcal.", "About 1050.4 kcal."):
        assert check_advice(t, f), t


def test_gain_users_never_get_eat_less_tips():
    for f in (F(meal=900, before=1000, goal=2000, goal_type="gain"), F(meal=900, before=1500, goal_type="gain")):
        for t in ("A smaller portion of the rice would help.", "Have half of it.", "Keep your next meal lighter."):
            assert reason(t, f) == "restrictive_tip", t
    g = F(meal=900, before=1000, goal_type="gain")
    assert "smaller" not in fallback_text(g) and "lighter" not in fallback_text(g)
    assert "lighter" not in fallback_text(F(meal=900, before=1000, goal_type="gain", eaten=True))


def test_unicode_and_spacing_tricks():
    for t in ("Do not  eat that.", "Don't\neat that.", "Don‘t eat that.", "Donʼt eat that.",
              "Sk​ip dinner.", "Ѕkip dinner.", "ＳＫＩＰ dinner."):
        assert reason(t) in ("blocked", "odd_characters"), repr(t)


def test_more_blocked_paraphrases():
    for t in ("Stop eating for today.", "Hold off on dinner.", "Go without the rice.", "Eat nothing else today.",
              "No more food today.", "Burn off those extra calories.", "Walk it off after.", "Work it off later.",
              "This will help you lose weight.", "Good for weight loss.", "You fasted well.", "A bit naughty!",
              "Rather sinful."):
        assert reason(t) == "blocked", t


def test_already_over_day_fallback_and_tiny_meals():
    for eaten, gt in product((False, True), ("lose", "maintain", "gain")):
        f = F(meal=0, before=2300, eaten=eaten, goal_type=gt, name="tea")
        text = fallback_text(f)
        assert text.startswith("Today was already") and "saves about 0" not in text and "smaller" not in text
        assert check_advice(text, f) == text
    tiny = F(meal=40, before=1980)                                # goes over by 20, half saves 20
    assert "saves about" not in fallback_text(tiny)


def test_exactly_at_goal_before_the_meal():
    for meal, eaten, gt in product((0, 300), (False, True), ("lose", "gain", "maintain")):
        f = F(meal=meal, before=2000, eaten=eaten, goal_type=gt)
        assert check_advice(fallback_text(f), f) == fallback_text(f), (meal, eaten, gt)
        assert not fallback_text(f).startswith("Today was already")


def test_probe_leftovers():
    for t in ("Maybe pass on the rice.", "Leave the rice and just have water.", "Just drink water instead.",
              "Your meal is too big; you are disgusting.", "That's gross.", "Don't be lazy."):
        assert reason(t) == "blocked", t
    assert reason("About ١٠٥٠ kcal.") == "odd_characters"
    assert check_advice("That would leave more room for later; 600 kcal so far.", F(meal=900, before=600))


def test_no_telling_people_they_are_done_eating():
    for t in ("Since you're finished eating for today, rest.", "You're done eating for the day.",
              "That's it for food today.", "Call it a day on food."):
        assert reason(t) == "blocked", t
