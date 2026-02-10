-- 더미 레코드 데이터
INSERT INTO records (id, user_id, creator_id, title, subtitle, google_photo_url, icloud_url, mybox_url, private_access_accounts)
VALUES
  ('c1111111-1111-1111-1111-111111111111', 'a1111111-1111-1111-1111-111111111111', 'a1111111-1111-1111-1111-111111111111',
   '할머니의 추억 앨범', '1950-2020 함께한 시간',
   'https://photos.google.com/share/example1', NULL, NULL, '{}'::text[]),

  ('c2222222-2222-2222-2222-222222222222', 'a1111111-1111-1111-1111-111111111111', 'a2222222-2222-2222-2222-222222222222',
   '아버지의 인생 기록', '소중한 순간들',
   NULL, 'https://www.icloud.com/sharedalbum/example2', NULL, '{}'::text[]),

  ('c3333333-3333-3333-3333-333333333333', 'a2222222-2222-2222-2222-222222222222', 'a2222222-2222-2222-2222-222222222222',
   '우리 가족 이야기', NULL,
   NULL, NULL, 'https://mybox.naver.com/share/example3', '{}'::text[]);
