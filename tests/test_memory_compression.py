import pytest
import sqlite3
import asyncio
from utils.history_manager import HistoryManager

@pytest.fixture
def memory_db(tmp_path):
    history = HistoryManager(
        project_name="test_compression",
        base_dir=str(tmp_path),
        context_window=50
    )
    yield history
    history.clear()

@pytest.mark.asyncio
async def test_compress_old_memories_threshold_not_met(memory_db):
    # Insert 10 messages (below default threshold of 40)
    for i in range(10):
        memory_db.add_message("user", f"Message {i}")
        
    compressed = await memory_db.compress_old_memories(threshold_msgs=40, compress_count=20)
    assert not compressed
    assert memory_db.get_stats()["total_messages"] == 10

@pytest.mark.asyncio
async def test_compress_old_memories_execution(memory_db):
    # Insert 50 messages
    for i in range(50):
        memory_db.add_message("user", f"Message {i}")
        
    assert memory_db.get_stats()["total_messages"] == 50
    
    # Mock AsyncOpenAI to avoid real LLM calls
    class MockMessage:
        content = "req:test|db:ok|status:compressed"
        
    class MockChoice:
        message = MockMessage()
        
    class MockCompletion:
        choices = [MockChoice()]
        
    class MockChat:
        completions = type('Obj', (), {'create': lambda *args, **kwargs: asyncio.sleep(0, result=MockCompletion())})()
        
    class MockClient:
        chat = MockChat()
        
    import unittest.mock as mock
    with mock.patch("openai.AsyncOpenAI", return_value=MockClient()):
        # Compress 20 oldest messages
        compressed = await memory_db.compress_old_memories(threshold_msgs=40, compress_count=20)
    
    assert compressed is True
    
    # 50 - 20 + 1 = 31 messages remaining
    assert memory_db.get_stats()["total_messages"] == 31
    
    # Verify the oldest message is now the compressed block
    history = memory_db.get_full_history()
    oldest = history[0]
    
    assert oldest["role"] == "system"
    assert "[COMPRESSED_MEMORY]" in oldest["content"]
    assert "req:test|db:ok|status:compressed" in oldest["content"]
