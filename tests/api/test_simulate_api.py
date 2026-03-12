def test_simulate_message_creates_dialog_and_returns_structured_response(client) -> None:
    response = client.post(
        "/simulate/message",
        json={
            "telegram_user_id": 5001,
            "telegram_chat_id": 5001,
            "username": "sim_user",
            "full_name": "Sim User",
            "text": "Сколько стоит внедрение?",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["lead_id"]
    assert body["incoming_message_id"]
    assert body["outgoing_message_id"]
    assert body["intent"] == "price_question"
    assert body["stage"] == "interested"
    assert isinstance(body["reply_text"], str)
