import base64
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

# Handle imports for both package and standalone execution
if __package__:
    # Running as part of a package
    from .langchain_client import (
        assess_document_authenticity_with_langchain,
        compare_fields_with_langchain,
        extract_fields_from_ocr,
    )
    from .ocr_utils import extract_text
else:
    # Running standalone - add current directory to path
    sys.path.insert(0, str(Path(__file__).parent))
    from langchain_client import (
        assess_document_authenticity_with_langchain,
        compare_fields_with_langchain,
        extract_fields_from_ocr,
    )
    from ocr_utils import extract_text

logger = logging.getLogger("kyc_verify_service")


def verify_driver_license(
    name: str,
    address: str,
    date_of_birth: str,
    driver_license_image: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Verify a driver's license by running OCR and comparing fields using LangChain.

    Args:
        name: User-provided name
        address: User-provided address
        date_of_birth: User-provided date of birth (format: YYYY-MM-DD)
        driver_license_image: Base64-encoded image string
        model: Optional LangChain model name override

    Returns:
        Dictionary with:
        - verified: bool indicating if verification passed
        - failure_reasons: list of strings explaining failures
        - match_details: dict with detailed comparison results
        - ocr_extracted_text: extracted OCR text (for debugging)
    """
    temp_file = None
    try:
        # Decode base64 image
        try:
            # Remove data URL prefix if present
            if driver_license_image.startswith("data:image"):
                driver_license_image = driver_license_image.split(",", 1)[1]

            image_bytes = base64.b64decode(driver_license_image)
        except Exception as exc:
            logger.error("Failed to decode base64 image: %s", exc)
            return {
                "verified": False,
                "failure_reasons": [f"Invalid base64 image encoding: {exc}"],
                "match_details": {},
                "ocr_extracted_text": "",
            }

        # Save to temporary file for OCR processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            temp_file = tmp.name
            tmp.write(image_bytes)

        # Run OCR
        try:
            ocr_result = extract_text(temp_file)
            ocr_lines = ocr_result.get("lines", [])
            ocr_text = ocr_result.get("text", "")
        except Exception as exc:
            logger.error("OCR extraction failed: %s", exc)
            return {
                "verified": False,
                "failure_reasons": [f"OCR extraction failed: {exc}"],
                "match_details": {},
                "ocr_extracted_text": "",
            }

        if not ocr_text:
            return {
                "verified": False,
                "failure_reasons": ["No text could be extracted from the document image"],
                "match_details": {},
                "ocr_extracted_text": "",
            }

        # Prepare expected data for LangChain
        expected_data = {
            "name": name,
            "address": address,
            "date_of_birth": date_of_birth,
        }

        # Extract specific fields (Name, Address, DOB) from OCR text using LangChain
        extracted_fields = extract_fields_from_ocr(
            ocr_text=ocr_text,
            model=model,
        )
        
        extracted_name = extracted_fields.get("name", "")
        extracted_address = extracted_fields.get("address", "")
        extracted_dob = extracted_fields.get("date_of_birth", "")
        
        logger.info(
            "Extracted fields - Name: '%s', Address: '%s', DOB: '%s'",
            extracted_name,
            extracted_address,
            extracted_dob,
        )

        # Run LangChain assessments using extracted fields
        authenticity_result = assess_document_authenticity_with_langchain(
            document_type="driver_license",
            extracted_text=ocr_text,
            expected_data=expected_data,
            model=model,
        )

        # Compare extracted fields with provided information
        field_comparison_result = compare_fields_with_langchain(
            ocr_text=f"Extracted Name: {extracted_name}\nExtracted Address: {extracted_address}\nExtracted Date of Birth: {extracted_dob}",
            provided_name=name,
            provided_address=address,
            provided_dob=date_of_birth,
            model=model,
        )

        # Analyze results and determine verification status
        failure_reasons = []
        verified = True

        # Check authenticity assessment
        authenticity_status = authenticity_result.get("status", "manual_review")
        authenticity_confidence = authenticity_result.get("confidence", 0.0)
        authenticity_flags = authenticity_result.get("flags", [])

        if authenticity_status == "rejected":
            verified = False
            failure_reasons.append(f"Document authenticity check failed: {authenticity_result.get('rationale', 'Document appears fraudulent')}")
        elif authenticity_status == "manual_review":
            if authenticity_confidence < 0.5:
                verified = False
                failure_reasons.append(f"Low authenticity confidence ({authenticity_confidence:.2f}): {authenticity_result.get('rationale', 'Unable to verify document authenticity')}")
        if authenticity_flags:
            for flag in authenticity_flags:
                if flag != "llm_evaluation_failed":  # Don't add this as a failure reason if other checks pass
                    failure_reasons.append(f"Authenticity flag: {flag}")

        # Check field comparisons
        name_match = field_comparison_result.get("name_match", {})
        address_match = field_comparison_result.get("address_match", {})
        dob_match = field_comparison_result.get("dob_match", {})

        name_status = name_match.get("status", "uncertain")
        address_status = address_match.get("status", "uncertain")
        dob_status = dob_match.get("status", "uncertain")

        if name_status == "mismatch":
            verified = False
            ocr_name = name_match.get("ocr_value", "not found")
            failure_reasons.append(f"Name mismatch: Expected '{name}', found '{ocr_name}'")
        elif name_status == "not_found":
            verified = False
            failure_reasons.append("Name not found in document")
        elif name_status == "uncertain":
            confidence = name_match.get("confidence", 0.0)
            if confidence < 0.6:
                verified = False
                failure_reasons.append(f"Name verification uncertain (confidence: {confidence:.2f}): {name_match.get('reason', 'Could not verify name')}")

        if address_status == "mismatch":
            verified = False
            ocr_address = address_match.get("ocr_value", "not found")
            failure_reasons.append(f"Address mismatch: Expected '{address}', found '{ocr_address}'")
        elif address_status == "not_found":
            verified = False
            failure_reasons.append("Address not found in document")
        elif address_status == "uncertain":
            confidence = address_match.get("confidence", 0.0)
            if confidence < 0.6:
                verified = False
                failure_reasons.append(f"Address verification uncertain (confidence: {confidence:.2f}): {address_match.get('reason', 'Could not verify address')}")

        if dob_status == "mismatch":
            verified = False
            ocr_dob = dob_match.get("ocr_value", "not found")
            failure_reasons.append(f"Date of birth mismatch: Expected '{date_of_birth}', found '{ocr_dob}'")
        elif dob_status == "not_found":
            verified = False
            failure_reasons.append("Date of birth not found in document")
        elif dob_status == "uncertain":
            confidence = dob_match.get("confidence", 0.0)
            if confidence < 0.6:
                verified = False
                failure_reasons.append(f"Date of birth verification uncertain (confidence: {confidence:.2f}): {dob_match.get('reason', 'Could not verify date of birth')}")

        # Build match details
        match_details = {
            "authenticity": {
                "status": authenticity_status,
                "confidence": authenticity_confidence,
                "rationale": authenticity_result.get("rationale", ""),
                "flags": authenticity_flags,
            },
            "extracted_fields": {
                "name": extracted_name,
                "address": extracted_address,
                "date_of_birth": extracted_dob,
            },
            "name": {
                "status": name_status,
                "ocr_value": name_match.get("ocr_value", ""),
                "confidence": name_match.get("confidence", 0.0),
                "reason": name_match.get("reason", ""),
            },
            "address": {
                "status": address_status,
                "ocr_value": address_match.get("ocr_value", ""),
                "confidence": address_match.get("confidence", 0.0),
                "reason": address_match.get("reason", ""),
            },
            "dob": {
                "status": dob_status,
                "ocr_value": dob_match.get("ocr_value", ""),
                "confidence": dob_match.get("confidence", 0.0),
                "reason": dob_match.get("reason", ""),
            },
            "model": field_comparison_result.get("model", model or "default"),
        }

        return {
            "verified": verified,
            "failure_reasons": failure_reasons if not verified else [],
            "match_details": match_details,
            "ocr_extracted_text": ocr_text,
        }

    except Exception as exc:
        logger.error("Unexpected error in driver license verification: %s", exc, exc_info=True)
        return {
            "verified": False,
            "failure_reasons": [f"Verification error: {exc}"],
            "match_details": {},
            "ocr_extracted_text": "",
        }

    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception as exc:
                logger.warning("Failed to delete temporary file %s: %s", temp_file, exc)

