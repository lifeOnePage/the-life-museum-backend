-- 더미 유저 데이터
INSERT INTO users (id, name, phone, email, is_active, is_verified, plan)
VALUES
  ('a1111111-1111-1111-1111-111111111111', '김영희', '010-1234-5678', 'younghee@example.com', true, true, 'premium'),
  ('a2222222-2222-2222-2222-222222222222', '이철수', '010-9876-5432', 'cheolsu@example.com', true, true, 'free'),
  ('a3333333-3333-3333-3333-333333333333', '박지민', '010-5555-1234', 'jimin@example.com', true, false, NULL);
