-- Demodaten für Anchors & Wearables (idempotent)

-- Anchors
INSERT INTO anchors (id, name, x, y, z)
VALUES
  ('A-01', 'Anchor 1',  5.0,  5.0, 2.5),
  ('A-02', 'Anchor 2', 5.0,  20.0, 2.5)
ON CONFLICT (id) DO NOTHING;

-- === Wearables (2 Stück) ===
INSERT INTO wearables (uid, person_ref, role)
VALUES
  ('W-01', 'alice',  'builder 1'),
  ('W-02', 'bob',    'builder 2')
ON CONFLICT (uid) DO NOTHING;
