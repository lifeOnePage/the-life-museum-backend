-- 더미 OAuth 계정 데이터
INSERT INTO oauth_accounts (id, user_id, provider, provider_user_id, access_token, refresh_token)
VALUES
  ('b1111111-1111-1111-1111-111111111111', 'a1111111-1111-1111-1111-111111111111', 'google', 'google_uid_001', 'access_token_001', 'refresh_token_001'),
  ('b2222222-2222-2222-2222-222222222222', 'a2222222-2222-2222-2222-222222222222', 'kakao', 'kakao_uid_002', 'access_token_002', 'refresh_token_002');
