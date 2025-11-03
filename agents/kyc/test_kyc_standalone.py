#!/usr/bin/env python3
"""
Standalone test script for the KYC agent.
Tests driver's license verification without requiring Redis or the full application stack.
"""

import argparse
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Set default Ollama URL and model BEFORE importing verify_service
if "OLLAMA_URL" not in os.environ:
    os.environ["OLLAMA_URL"] = "http://localhost:11434"
if "KYC_LLM_MODEL" not in os.environ:
    os.environ["KYC_LLM_MODEL"] = "llama3.2"

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from verify_service import verify_driver_license

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [TEST] %(levelname)s: %(message)s",
)
logger = logging.getLogger("test_kyc")


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


def encode_image_to_base64(image_path: str) -> str:
    """Encode an image file to base64 string."""
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
            return base64.b64encode(image_bytes).decode("utf-8")
    except FileNotFoundError:
        logger.error("Image file not found: %s", image_path)
        sys.exit(1)
    except Exception as e:
        logger.error("Failed to encode image: %s", e)
        sys.exit(1)


def create_sample_data() -> Dict[str, Any]:
    """Create sample test data matching Saskatchewan driver's license."""
    return {
        "name": "Jane Sample",
        "address": "1 Anywhere St. Regina, SK S4P 2N7",
        "date_of_birth": "1988-08-15",
        "driver_license_image": "",  # Will need to be provided via --image-file
    }


def print_verification_results(result: Dict[str, Any], show_ocr: bool = False) -> None:
    """Print verification results in a formatted way."""
    verified = result.get("verified", False)
    failure_reasons = result.get("failure_reasons", [])
    match_details = result.get("match_details", {})
    ocr_text = result.get("ocr_extracted_text", "")

    print("\n" + "=" * 80)
    print("KYC VERIFICATION RESULTS")
    print("=" * 80)

    if verified:
        print("\n✅ VERIFICATION PASSED")
    else:
        print("\n❌ VERIFICATION FAILED")

    if failure_reasons:
        print("\n📋 Failure Reasons:")
        for i, reason in enumerate(failure_reasons, 1):
            print(f"   {i}. {reason}")

    if match_details:
        print("\n🔍 Match Details:")
        print("-" * 80)

        # Authenticity
        authenticity = match_details.get("authenticity", {})
        if authenticity:
            print(f"\n📄 Document Authenticity:")
            print(f"   Status:     {authenticity.get('status', 'N/A')}")
            print(f"   Confidence: {authenticity.get('confidence', 0.0):.2f}")
            rationale = authenticity.get("rationale", "")
            if rationale:
                print(f"   Rationale:  {rationale}")
            flags = authenticity.get("flags", [])
            if flags:
                print(f"   Flags:      {', '.join(flags)}")

        # Name
        name_match = match_details.get("name", {})
        if name_match:
            print(f"\n👤 Name:")
            print(f"   Status:     {name_match.get('status', 'N/A')}")
            print(f"   OCR Value:  {name_match.get('ocr_value', 'N/A')}")
            print(f"   Confidence: {name_match.get('confidence', 0.0):.2f}")
            reason = name_match.get("reason", "")
            if reason:
                print(f"   Reason:     {reason}")

        # Address
        address_match = match_details.get("address", {})
        if address_match:
            print(f"\n📍 Address:")
            print(f"   Status:     {address_match.get('status', 'N/A')}")
            print(f"   OCR Value:  {address_match.get('ocr_value', 'N/A')}")
            print(f"   Confidence: {address_match.get('confidence', 0.0):.2f}")
            reason = address_match.get("reason", "")
            if reason:
                print(f"   Reason:     {reason}")

        # Date of Birth
        dob_match = match_details.get("dob", {})
        if dob_match:
            print(f"\n🎂 Date of Birth:")
            print(f"   Status:     {dob_match.get('status', 'N/A')}")
            print(f"   OCR Value:  {dob_match.get('ocr_value', 'N/A')}")
            print(f"   Confidence: {dob_match.get('confidence', 0.0):.2f}")
            reason = dob_match.get("reason", "")
            if reason:
                print(f"   Reason:     {reason}")

        model = match_details.get("model", "N/A")
        print(f"\n🤖 Model Used: {model}")

    if show_ocr and ocr_text:
        print("\n" + "=" * 80)
        print("OCR EXTRACTED TEXT")
        print("=" * 80)
        print(ocr_text)

    print("\n" + "=" * 80)


def main() -> None:
    """Main test function."""
    parser = argparse.ArgumentParser(
        description="Test KYC agent independently",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with sample data (requires --image-file)
  python test_kyc_standalone.py --sample --image-file test-id.jpg

  # Test with JSON file
  python test_kyc_standalone.py --input sample_test_data.json --image-file test-id.jpg

  # Test with individual fields
  python test_kyc_standalone.py --name "Jane Sample" --address "1 Anywhere St. Regina, SK S4P 2N7" --dob "1988-08-15" --image-file test-id.jpg

  # Test with inline JSON
  python test_kyc_standalone.py --json '{"name":"Jane Sample","address":"1 Anywhere St. Regina, SK S4P 2N7","date_of_birth":"1988-08-15","driver_license_image":"BASE64..."}'
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
        "--name",
        type=str,
        help="User's full name",
    )
    parser.add_argument(
        "--address",
        type=str,
        help="User's address",
    )
    parser.add_argument(
        "--dob",
        type=str,
        help="Date of birth (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--image",
        type=str,
        help="Base64-encoded driver's license image",
    )
    parser.add_argument(
        "--image-file",
        type=str,
        help="Path to driver's license image file (will be converted to base64)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path to save results (optional)",
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
    parser.add_argument(
        "--show-ocr",
        action="store_true",
        help="Show OCR extracted text in output",
    )

    args = parser.parse_args()

    # Set Ollama URL and model environment variables
    os.environ["OLLAMA_URL"] = args.ollama_url
    os.environ["KYC_LLM_MODEL"] = args.model

    # Display Ollama connection info
    print(f"\n🔗 Connecting to Ollama at: {args.ollama_url}")
    print(f"📦 Using model: {args.model}")
    print("   (Make sure Ollama is running! Use --ollama-url and --model to change settings)\n")

    # Determine input source
    test_data: Dict[str, Any] = {}

    if args.json:
        try:
            test_data = json.loads(args.json)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON string: %s", e)
            sys.exit(1)
    elif args.input:
        test_data = load_test_data(args.input)
    elif args.sample:
        test_data = create_sample_data()
    elif args.name or args.address or args.dob or args.image or args.image_file:
        # Build from individual arguments
        test_data = {
            "name": args.name or "",
            "address": args.address or "",
            "date_of_birth": args.dob or "",
            "driver_license_image": args.image or "",
        }
    else:
        # Default to sample data
        logger.info("No input specified, using sample data. Use --help for options.")
        test_data = create_sample_data()

    # Handle image file if provided
    if args.image_file and not test_data.get("driver_license_image"):
        logger.info("Encoding image file to base64: %s", args.image_file)
        test_data["driver_license_image"] = encode_image_to_base64(args.image_file)
    elif args.image_file:
        # Override even if image was provided in JSON
        logger.info("Overriding image with file: %s", args.image_file)
        test_data["driver_license_image"] = encode_image_to_base64(args.image_file)

    # Validate required fields
    required_fields = ["name", "address", "date_of_birth", "driver_license_image"]
    missing_fields = [f for f in required_fields if not test_data.get(f)]
    if missing_fields:
        logger.error("Missing required fields: %s", ", ".join(missing_fields))
        if "driver_license_image" in missing_fields:
            logger.error("Hint: Use --image-file to provide an image file")
        sys.exit(1)

    # Display input (without showing full base64 image)
    print("\n" + "=" * 80)
    print("KYC AGENT TEST - STANDALONE MODE")
    print("=" * 80)
    print("\n📥 Input Data:")
    display_data = test_data.copy()
    if display_data.get("driver_license_image"):
        img_len = len(display_data["driver_license_image"])
        display_data["driver_license_image"] = f"<base64 image, {img_len} chars>"
    print(json.dumps(display_data, indent=2))

    # Run verification
    print("\n🔍 Running verification...")
    try:
        result = verify_driver_license(
            name=test_data["name"],
            address=test_data["address"],
            date_of_birth=test_data["date_of_birth"],
            driver_license_image=test_data["driver_license_image"],
            model=args.model,
        )

        print_verification_results(result, show_ocr=args.show_ocr)

        # Save to file if requested
        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2)
            print(f"\n💾 Results saved to: {output_path}")

        print("\n✅ Test completed successfully!")
        sys.exit(0 if result.get("verified", False) else 1)

    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "404" in error_msg:
            logger.error("\n❌ Model '%s' not found!", args.model)
            print("\n💡 Troubleshooting:")
            print(f"   1. Check if the model is available: ollama list")
            print(f"   2. Pull the model if needed: ollama pull {args.model}")
            print(f"   3. Try a different model name (e.g., llama3.1:latest, llama3.2)")
            print(f"   4. Use --model flag to specify a different model")
            print(f"\n   Example: python test_kyc_standalone.py --model llama3.2 --sample --image-file test-id.jpg")
        else:
            logger.error("Test failed with error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

