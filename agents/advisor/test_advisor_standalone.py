#!/usr/bin/env python3
"""
Standalone test script for the advisor agent.
Tests credit card recommendations without requiring Redis or the full application stack.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Set default Ollama URL and model BEFORE importing langchain_client
# (langchain_client reads these at import time)
if "OLLAMA_URL" not in os.environ:
    os.environ["OLLAMA_URL"] = "http://localhost:11434"
if "ADVISOR_LLM_MODEL" not in os.environ:
    os.environ["ADVISOR_LLM_MODEL"] = "llama3.2"

from credit_cards import CREDIT_CARDS
import langchain_client
from langchain_client import get_credit_card_recommendations

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [TEST] %(levelname)s: %(message)s",
)
logger = logging.getLogger("test_advisor")


def load_test_data(file_path: str) -> Dict[str, Any]:
    """Load test data from JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("File not found: %s", file_path)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in file %s: %s", file_path, e)
        sys.exit(1)


def create_sample_data() -> Dict[str, Any]:
    """Create sample test data."""
    return {
        "case_id": "test_001",
        "address": "123 Main Street, Toronto, ON, Canada",
        "yearly_income": 45000,
        "questions": {
            "q1_credit_history": "established",
            "q2_payment_style": "full payment",
            "q3_cashback": "yes",
            "q4_travel": "no",
            "q5_simple_card": "yes",
        },
    }


def print_recommendations(recommendations: Dict[str, Any]) -> None:
    """Print recommendations in a formatted way."""
    recs = recommendations.get("recommendations", [])
    if not recs:
        print("\n❌ No recommendations returned.")
        return

    print(f"\n✅ Found {len(recs)} recommendation(s):\n")
    print("=" * 80)

    for i, rec in enumerate(recs, 1):
        print(f"\n📋 Recommendation #{i}:")
        print(f"   Card Name:      {rec.get('card_name', 'N/A')}")
        print(f"   Annual Fee:     {rec.get('annual_fee', 'N/A')}")
        print(f"   Interest Rate:  {rec.get('interest_rate', 'N/A')}")
        print(f"   Rewards:        {rec.get('rewards', 'N/A')}")
        print(f"   Requirements:   {rec.get('requirements', 'N/A')}")
        print(f"   Why Recommended: {rec.get('why_recommended', 'N/A')}")
        print("-" * 80)

    print("\n" + "=" * 80)


def main() -> None:
    """Main test function."""
    parser = argparse.ArgumentParser(
        description="Test advisor agent independently",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with sample data
  python test_advisor_standalone.py

  # Test with JSON file
  python test_advisor_standalone.py --input sample_data.json

  # Test with inline JSON
  python test_advisor_standalone.py --json '{"case_id":"test","address":"123 Main","yearly_income":50000,"questions":{"q1_credit_history":"established","q2_payment_style":"full payment","q3_cashback":"yes","q4_travel":"no","q5_simple_card":"no"}}'
        """,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        help="Path to JSON file containing test data",
    )
    parser.add_argument(
        "--json",
        "-j",
        type=str,
        help="Inline JSON string with test data",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Use built-in sample data",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path to save recommendations (optional)",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama service URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="llama3.2",
        help="Ollama model to use (default: llama3.2). Note: Use 'llama3.2' not 'llama3.2:latest'",
    )

    args = parser.parse_args()

    # Set Ollama URL and model environment variables for langchain_client
    os.environ["OLLAMA_URL"] = args.ollama_url
    os.environ["ADVISOR_LLM_MODEL"] = args.model
    
    # Update module-level variables in langchain_client (they're read at import time)
    langchain_client.OLLAMA_URL = args.ollama_url
    langchain_client.DEFAULT_MODEL = args.model
    
    # Display Ollama connection info
    print(f"\n🔗 Connecting to Ollama at: {args.ollama_url}")
    print(f"📦 Using model: {args.model}")
    print("   (Make sure Ollama is running! Use --ollama-url and --model to change settings)\n")

    # Determine input source
    if args.json:
        try:
            user_data = json.loads(args.json)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON string: %s", e)
            sys.exit(1)
    elif args.input:
        user_data = load_test_data(args.input)
    elif args.sample:
        user_data = create_sample_data()
    else:
        # Default to sample data
        logger.info("No input specified, using sample data. Use --help for options.")
        user_data = create_sample_data()

    # Validate required fields
    required_fields = ["case_id", "address", "yearly_income", "questions"]
    missing_fields = [f for f in required_fields if f not in user_data]
    if missing_fields:
        logger.error("Missing required fields: %s", ", ".join(missing_fields))
        sys.exit(1)

    # Validate questions
    questions = user_data.get("questions", {})
    if not isinstance(questions, dict):
        logger.error("'questions' must be a dictionary")
        sys.exit(1)

    required_questions = [
        "q1_credit_history",
        "q2_payment_style",
        "q3_cashback",
        "q4_travel",
        "q5_simple_card",
    ]
    missing_questions = [q for q in required_questions if q not in questions]
    if missing_questions:
        logger.error("Missing required questions: %s", ", ".join(missing_questions))
        sys.exit(1)

    # Display input
    print("\n" + "=" * 80)
    print("ADVISOR AGENT TEST - STANDALONE MODE")
    print("=" * 80)
    print("\n📥 Input Data:")
    print(json.dumps(user_data, indent=2))

    # Get recommendations
    print("\n🔍 Processing recommendations...")
    try:
        # Call Langchain client directly (no Redis needed)
        recommendations = get_credit_card_recommendations(user_data, CREDIT_CARDS)
        print_recommendations(recommendations)

        # Save to file if requested
        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(recommendations, f, indent=2)
            print(f"\n💾 Recommendations saved to: {output_path}")

        print("\n✅ Test completed successfully!")
        sys.exit(0)

    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "404" in error_msg:
            logger.error("\n❌ Model '%s' not found!", args.model)
            print("\n💡 Troubleshooting:")
            print(f"   1. Check if the model is available: ollama list")
            print(f"   2. Pull the model if needed: ollama pull {args.model}")
            print(f"   3. Try a different model name (e.g., llama3.2:latest, llama3.2:3b)")
            print(f"   4. Use --model flag to specify a different model")
            print(f"\n   Example: python test_advisor_standalone.py --model llama3")
        else:
            logger.error("Test failed with error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

