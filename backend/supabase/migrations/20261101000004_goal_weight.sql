-- The weight a calorie goal was worked out from, so the app can offer a new goal
-- once the logged weight has moved 2 kg or more. Null for a goal typed in by hand.
alter table public.client_settings
  add column goal_weight_kg numeric(6,2)
    check (goal_weight_kg is null or goal_weight_kg between 30 and 300);
