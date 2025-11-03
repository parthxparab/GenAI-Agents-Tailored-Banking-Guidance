from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

from langchain_ollama import ChatOllama
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger("kyc_langchain_client")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("KYC_LLM_MODEL", "llama3")
KYC_LLM_MODEL = os.getenv("KYC_LLM_MODEL", DEFAULT_MODEL)


def _build_authenticity_prompt_template() -> ChatPromptTemplate:
    """Build the Langchain prompt template for document authenticity assessment."""
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a document verification expert working for a regulated bank.
Your task is to assess the authenticity of identity documents by analyzing OCR-extracted text.

CRITICAL RULES:
1. Examine the OCR text for signs of authenticity or fraud
2. Look for proper formatting, expected fields, and document structure
3. Identify suspicious patterns, missing information, or inconsistencies
4. Return structured JSON with status, confidence, rationale, and flags

Status values:
- "verified": Document appears genuine and authentic
- "manual_review": Uncertain or requires human oversight
- "rejected": Document appears fraudulent or incorrect

Confidence should be a float between 0.0 and 1.0 indicating your certainty.""",
            ),
            (
                "user",
                """Document Type: {document_type}

OCR Extracted Text:
{extracted_text}

Expected User Data:
{expected_data}

Analyze this document for authenticity. Return ONLY valid JSON matching this structure:
{{
  "status": "verified|manual_review|rejected",
  "confidence": 0.0-1.0,
  "rationale": "brief explanation of your assessment",
  "flags": ["list", "of", "concern", "flags", "if", "any"]
}}

If no concerns, use empty array for flags.""",
            ),
        ]
    )


def _build_field_extraction_prompt_template() -> ChatPromptTemplate:
    """Build the Langchain prompt template for extracting specific fields from OCR text."""
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a document data extraction specialist working for a regulated bank.
Your task is to extract specific fields (Name, Address, Date of Birth) from OCR-extracted text from a driver's license.

CRITICAL RULES:
1. Extract ONLY the Name, Address, and Date of Birth fields
2. Ignore all other information (license number, expiry date, restrictions, etc.)
3. For Name: Look for patterns like "LASTNAME, FIRSTNAME" or "FIRSTNAME LASTNAME"
4. For Address: 
   - Extract the complete street address, city, province/state, and postal code
   - Street number will ALWAYS be in front of the street name (e.g., "123 Main St" not "Main St 123")
   - Unit numbers (apartment, suite, etc.) are optional and may not always be present
   - Include street number, street name, city, province/state, and postal code
   - Format: "Street Number Street Name, City, Province Postal Code" or "Unit Street Number Street Name, City, Province Postal Code"
5. For Date of Birth: Look for dates in formats like YYYY-MM-DD, YYYY/MM/DD, DD MMM YYYY, YYYY MMM DD (e.g., "1988 AUG 15"), etc.
   - Always normalize to YYYY-MM-DD format in the output (e.g., "1988 AUG 15" becomes "1988-08-15")
6. If a field is not found, return empty string
7. Return structured JSON with the extracted values""",
            ),
            (
                "user",
                """OCR Extracted Text from Driver's License:
{ocr_text}

Extract ONLY the Name, Address, and Date of Birth from this text. 

CRITICAL: Return ONLY valid JSON. Do NOT include any explanations, code, markdown, or other text before or after the JSON. Start directly with {{ and end with }}.

Return ONLY valid JSON matching this exact structure:
{{
  "name": "extracted name exactly as it appears",
  "address": "extracted address exactly as it appears",
  "date_of_birth": "extracted date of birth in YYYY-MM-DD format (convert if needed)"
}}

If a field is not found, use empty string "". For date_of_birth, normalize to YYYY-MM-DD format.""",
            ),
        ]
    )


def extract_fields_from_ocr(
    ocr_text: str,
    model: Optional[str] = None,
) -> Dict[str, str]:
    """
    Extract Name, Address, and Date of Birth specifically from OCR text using LangChain.

    Args:
        ocr_text: OCR-extracted text from document
        model: Optional model name override

    Returns:
        Dictionary with extracted name, address, and date_of_birth fields
    """
    try:
        # Read model and URL dynamically
        model_name = model or os.getenv("KYC_LLM_MODEL", DEFAULT_MODEL)
        ollama_url = os.getenv("OLLAMA_URL", OLLAMA_URL)

        logger.info("Extracting fields from OCR with model: %s, URL: %s", model_name, ollama_url)

        # Initialize LLM
        llm = ChatOllama(
            model=model_name,
            base_url=ollama_url,
            temperature=0.1,  # Very low temperature for precise extraction
        )

        # Create parser
        parser = JsonOutputParser()

        # Build chain
        prompt = _build_field_extraction_prompt_template()
        chain = prompt | llm | parser

        # Invoke chain
        raw_response = chain.invoke(
            {
                "ocr_text": ocr_text,
            }
        )

        # Handle case where LLM returns non-dict (e.g., string with JSON or code)
        response = raw_response
        if isinstance(raw_response, str):
            logger.warning("Received string response in field extraction, attempting to extract JSON")
            # Try to extract JSON from the string (remove markdown code blocks, explanations, etc.)
            # Remove markdown code blocks if present
            cleaned = re.sub(r'```json\s*', '', raw_response)
            cleaned = re.sub(r'```\s*', '', cleaned)
            cleaned = re.sub(r'```python\s*.*?```', '', cleaned, flags=re.DOTALL)
            # Try to find JSON object
            json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if json_match:
                try:
                    response = json.loads(json_match.group(0))
                    logger.info("Successfully extracted JSON from string response")
                except json.JSONDecodeError as parse_error:
                    logger.error("Failed to parse JSON from string response: %s", parse_error)
                    raise ValueError(f"Could not parse JSON from response: {cleaned[:200]}")
            else:
                raise ValueError(f"Could not find JSON in response: {cleaned[:200]}")

        # Validate response structure
        if not isinstance(response, dict):
            raise ValueError(f"Expected dict response, got {type(response)}")

        # Normalize and return extracted fields
        return {
            "name": response.get("name", "").strip(),
            "address": response.get("address", "").strip(),
            "date_of_birth": response.get("date_of_birth", "").strip(),
        }

    except json.JSONDecodeError as exc:
        logger.error("JSON decode error in LangChain field extraction: %s", exc, exc_info=True)
        return {
            "name": "",
            "address": "",
            "date_of_birth": "",
        }
    except Exception as exc:
        logger.error("Error in LangChain field extraction: %s", exc, exc_info=True)
        return {
            "name": "",
            "address": "",
            "date_of_birth": "",
        }


def _build_field_comparison_prompt_template() -> ChatPromptTemplate:
    """Build the Langchain prompt template for field comparison."""
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """You are a data verification specialist working for a regulated bank.
Your task is to compare OCR-extracted fields from an identity document with provided user information.

CRITICAL RULES:
1. Compare each field (name, address, date of birth) independently
2. Account for OCR errors, formatting differences, and variations
3. Be VERY flexible with formatting - the extracted values may be correct even if formatted differently
4. For Address:
   - Ignore formatting differences (commas, periods, spacing)
   - Compare street number, street name, city, province/state, and postal code
   - Street number always comes first, unit numbers are optional
   - If the core address components match, mark as "match" even if punctuation/spacing differs
   - Examples: "1 Anywhere St. Regina, SK S4P 2N7" matches "1 Anywhere St, Regina, SK S4P 2N7"
5. For Date of Birth:
   - Accept any valid date format (YYYY-MM-DD, YYYY/MM/DD, YYYY MMM DD, etc.)
   - If the dates represent the same day, mark as "match" regardless of format
   - Examples: "1988-08-15" matches "1988 AUG 15" or "1988/08/15" or "1988-08-15"
6. For Name:
   - Ignore case differences
   - Handle variations like "LASTNAME, FIRSTNAME" vs "FIRSTNAME LASTNAME"
   - If names match (accounting for order and case), mark as "match"
7. Return structured JSON with match status for each field

For each field, determine if it matches (considering OCR imperfections):
- "match": Fields match (accounting for formatting differences) - use this when values are essentially the same
- "mismatch": Fields clearly do not match (different street names, different dates, different names)
- "not_found": Field not found in OCR text
- "uncertain": Cannot determine with confidence (use sparingly, prefer "match" if values are similar)""",
            ),
            (
                "user",
                """Extracted Fields from OCR:
{ocr_text}

Provided User Information:
- Name: {provided_name}
- Address: {provided_address}
- Date of Birth: {provided_dob}

Compare the extracted fields with the provided information. IMPORTANT: 
- If the address components match (street number, street name, city, province, postal code), mark as "match" even if punctuation differs
- If the dates represent the same day, mark as "match" regardless of format
- If the names match (same person, accounting for order/case), mark as "match"
- Only mark as "mismatch" if values are clearly different (different street names, different dates, different people)
- Use high confidence (0.8+) when values match semantically

CRITICAL: Return ONLY valid JSON. Do NOT include any explanations, code, markdown, or other text before or after the JSON. Start directly with {{ and end with }}.

Return ONLY valid JSON matching this exact structure:
{{
  "name_match": {{
    "status": "match|mismatch|not_found|uncertain",
    "ocr_value": "what was found in OCR",
    "confidence": 0.0-1.0,
    "reason": "explanation if mismatch or uncertain"
  }},
  "address_match": {{
    "status": "match|mismatch|not_found|uncertain",
    "ocr_value": "what was found in OCR",
    "confidence": 0.0-1.0,
    "reason": "explanation if mismatch or uncertain"
  }},
  "dob_match": {{
    "status": "match|mismatch|not_found|uncertain",
    "ocr_value": "what was found in OCR",
    "confidence": 0.0-1.0,
    "reason": "explanation if mismatch or uncertain"
  }}
}}""",
            ),
        ]
    )


def assess_document_authenticity_with_langchain(
    document_type: str,
    extracted_text: str,
    expected_data: Dict[str, Any],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Assess document authenticity using LangChain with Ollama.

    Args:
        document_type: Type of document (e.g., "driver_license")
        extracted_text: Full OCR-extracted text from document
        expected_data: Dictionary with expected user data (name, address, dob)
        model: Optional model name override

    Returns:
        Dictionary with status, confidence, rationale, flags, and model
    """
    try:
        # Read model and URL dynamically
        model_name = model or os.getenv("KYC_LLM_MODEL", DEFAULT_MODEL)
        ollama_url = os.getenv("OLLAMA_URL", OLLAMA_URL)

        logger.info("Assessing document authenticity with model: %s, URL: %s", model_name, ollama_url)

        # Initialize LLM
        llm = ChatOllama(
            model=model_name,
            base_url=ollama_url,
            temperature=0.3,  # Lower temperature for more consistent verification
        )

        # Create parser
        parser = JsonOutputParser()

        # Build chain
        prompt = _build_authenticity_prompt_template()
        chain = prompt | llm | parser

        # Invoke chain
        expected_data_str = json.dumps(expected_data, indent=2)
        response = chain.invoke(
            {
                "document_type": document_type,
                "extracted_text": extracted_text,
                "expected_data": expected_data_str,
            }
        )

        # Validate and normalize response
        if not isinstance(response, dict):
            raise ValueError(f"Expected dict response, got {type(response)}")

        return {
            "status": response.get("status", "manual_review"),
            "confidence": float(response.get("confidence", 0.0)),
            "rationale": response.get("rationale", ""),
            "flags": response.get("flags", []),
            "model": model_name,
        }

    except Exception as exc:
        logger.error("Error in LangChain document authenticity assessment: %s", exc, exc_info=True)
        return {
            "status": "manual_review",
            "confidence": 0.0,
            "rationale": f"LangChain assessment error: {exc}",
            "flags": ["llm_evaluation_failed"],
            "model": model or DEFAULT_MODEL,
        }


def compare_fields_with_langchain(
    ocr_text: str,
    provided_name: str,
    provided_address: str,
    provided_dob: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare OCR-extracted fields with provided user information using LangChain.

    Args:
        ocr_text: OCR-extracted text from document
        provided_name: User-provided name
        provided_address: User-provided address
        provided_dob: User-provided date of birth
        model: Optional model name override

    Returns:
        Dictionary with comparison results for each field (name, address, dob)
    """
    try:
        # Read model and URL dynamically
        model_name = model or os.getenv("KYC_LLM_MODEL", DEFAULT_MODEL)
        ollama_url = os.getenv("OLLAMA_URL", OLLAMA_URL)

        logger.info("Comparing fields with LangChain using model: %s, URL: %s", model_name, ollama_url)

        # Initialize LLM
        llm = ChatOllama(
            model=model_name,
            base_url=ollama_url,
            temperature=0.3,  # Lower temperature for more consistent comparisons
        )

        # Create parser
        parser = JsonOutputParser()

        # Build chain
        prompt = _build_field_comparison_prompt_template()
        chain = prompt | llm | parser

        # Invoke chain
        raw_response = chain.invoke(
            {
                "ocr_text": ocr_text,
                "provided_name": provided_name,
                "provided_address": provided_address,
                "provided_dob": provided_dob,
            }
        )

        # Handle case where LLM returns non-dict (e.g., string with JSON or code)
        response = raw_response
        if isinstance(raw_response, str):
            logger.warning("Received string response, attempting to extract JSON")
            # Try to extract JSON from the string (remove markdown code blocks, explanations, etc.)
            # Remove markdown code blocks if present
            cleaned = re.sub(r'```json\s*', '', raw_response)
            cleaned = re.sub(r'```\s*', '', cleaned)
            cleaned = re.sub(r'```python\s*.*?```', '', cleaned, flags=re.DOTALL)
            # Try to find JSON object
            json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if json_match:
                try:
                    response = json.loads(json_match.group(0))
                    logger.info("Successfully extracted JSON from string response")
                except json.JSONDecodeError as parse_error:
                    logger.error("Failed to parse JSON from string response: %s", parse_error)
                    raise ValueError(f"Could not parse JSON from response: {cleaned[:200]}")
            else:
                raise ValueError(f"Could not find JSON in response: {cleaned[:200]}")

        # Validate response structure
        if not isinstance(response, dict):
            raise ValueError(f"Expected dict response, got {type(response)}")

        # Normalize field comparison results
        result = {
            "name_match": response.get("name_match", {}),
            "address_match": response.get("address_match", {}),
            "dob_match": response.get("dob_match", {}),
            "model": model_name,
        }

        return result

    except json.JSONDecodeError as exc:
        logger.error("JSON decode error in LangChain field comparison: %s", exc, exc_info=True)
        return {
            "name_match": {
                "status": "uncertain",
                "ocr_value": "",
                "confidence": 0.0,
                "reason": f"LangChain JSON parsing error: {exc}",
            },
            "address_match": {
                "status": "uncertain",
                "ocr_value": "",
                "confidence": 0.0,
                "reason": f"LangChain JSON parsing error: {exc}",
            },
            "dob_match": {
                "status": "uncertain",
                "ocr_value": "",
                "confidence": 0.0,
                "reason": f"LangChain JSON parsing error: {exc}",
            },
            "model": model or DEFAULT_MODEL,
        }
    except Exception as exc:
        logger.error("Error in LangChain field comparison: %s", exc, exc_info=True)
        return {
            "name_match": {
                "status": "uncertain",
                "ocr_value": "",
                "confidence": 0.0,
                "reason": f"LangChain comparison error: {exc}",
            },
            "address_match": {
                "status": "uncertain",
                "ocr_value": "",
                "confidence": 0.0,
                "reason": f"LangChain comparison error: {exc}",
            },
            "dob_match": {
                "status": "uncertain",
                "ocr_value": "",
                "confidence": 0.0,
                "reason": f"LangChain comparison error: {exc}",
            },
            "model": model or DEFAULT_MODEL,
        }

