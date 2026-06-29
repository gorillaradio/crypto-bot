from app.db.models import ShareLink


def test_share_link_roundtrip(db_session):
    link = ShareLink(label="amici", token="tok-123")
    db_session.add(link)
    db_session.commit()
    got = db_session.query(ShareLink).filter_by(token="tok-123").one()
    assert got.id is not None
    assert got.label == "amici"
    assert got.created_at is not None


def test_share_link_label_optional(db_session):
    link = ShareLink(token="tok-456")
    db_session.add(link)
    db_session.commit()
    assert db_session.query(ShareLink).filter_by(token="tok-456").one().label is None
