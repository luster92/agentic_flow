import sys
import json
import logging

# Configure logging to stderr (since stdout is used for protocol)
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("demo_server")

def main():
    logger.info("Starting Demo MCP Server...")
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            request = json.loads(line)
            method = request.get("method")
            msg_id = request.get("id")
            
            logger.info(f"Received request: {method}")
            
            response = None
            
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05", # Hypothetical version
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "demo-server",
                            "version": "1.0.0"
                        }
                    }
                }
            
            elif method == "notifications/initialized":
                # No response needed for notification
                continue
                
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": [
                            {
                                "name": "add_numbers",
                                "description": "Adds two numbers together.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "a": {"type": "number"},
                                        "b": {"type": "number"}
                                    },
                                    "required": ["a", "b"]
                                }
                            }
                        ]
                    }
                }
                
            elif method == "tools/call":
                params = request.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})
                
                if name == "add_numbers":
                    a = args.get("a", 0)
                    b = args.get("b", 0)
                    result_text = str(a + b)
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": result_text
                                }
                            ]
                        }
                    }
                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32601,
                            "message": f"Tool not found: {name}"
                        }
                    }
            
            elif method == "ping":
                 response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {}
                }

            else:
                 # Ignore other methods or return error
                 if msg_id is not None:
                     response = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32601,
                            "message": "Method not found"
                        }
                    }

            if response:
                print(json.dumps(response), flush=True)

        except json.JSONDecodeError:
            logger.error("Failed to decode JSON")
            continue
        except Exception as e:
            logger.error(f"Server error: {e}")
            break

if __name__ == "__main__":
    main()
