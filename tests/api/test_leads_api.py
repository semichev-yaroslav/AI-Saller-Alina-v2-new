def _simulate(client, user_id: int, text: str, username: str) -> None:
    response = client.post(
        "/simulate/message",
        json={
            "telegram_user_id": user_id,
            "telegram_chat_id": user_id,
            "username": username,
            "full_name": "Test Lead",
            "text": text,
        },
    )
    assert response.status_code == 200


def test_leads_list_get_and_messages(client) -> None:
    _simulate(client, 7001, "Нужен AI-бот", "lead_a")
    _simulate(client, 7002, "Сколько стоит?", "lead_b")

    leads_resp = client.get("/leads")
    assert leads_resp.status_code == 200
    leads = leads_resp.json()
    assert len(leads) == 2

    lead_id = leads[0]["id"]

    lead_resp = client.get(f"/leads/{lead_id}")
    assert lead_resp.status_code == 200
    assert lead_resp.json()["id"] == lead_id

    messages_resp = client.get(f"/leads/{lead_id}/messages")
    assert messages_resp.status_code == 200
    messages = messages_resp.json()
    assert len(messages) >= 2


def test_leads_filters_by_stage_and_search(client) -> None:
    _simulate(client, 8001, "Сколько стоит?", "price_lead")
    _simulate(client, 8002, "Нужен AI-бот", "service_lead")

    filtered = client.get("/leads", params={"stage": "interested"})
    assert filtered.status_code == 200
    leads = filtered.json()
    assert all(item["stage"] == "interested" for item in leads)

    searched = client.get("/leads", params={"search": "price_"})
    assert searched.status_code == 200
    leads = searched.json()
    assert len(leads) == 1
    assert leads[0]["username"] == "price_lead"
