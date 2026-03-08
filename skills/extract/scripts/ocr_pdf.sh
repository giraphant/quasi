#!/bin/bash
#
# OCR PDF Script
# Converts scanned PDF to searchable PDF with text layer
#
# Usage: ./ocr_pdf.sh input.pdf [output.pdf] [language]
#
# Examples:
#   ./ocr_pdf.sh scan.pdf                    # Output: scan_ocr.pdf (Chinese+English)
#   ./ocr_pdf.sh scan.pdf output.pdf         # Specify output file
#   ./ocr_pdf.sh scan.pdf output.pdf eng     # English only
#   ./ocr_pdf.sh scan.pdf output.pdf chi_sim # Simplified Chinese only
#

set -e

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

# Check dependencies
check_deps() {
    local missing=()

    if ! command -v ocrmypdf &> /dev/null; then
        missing+=("ocrmypdf")
    fi

    if ! command -v tesseract &> /dev/null; then
        missing+=("tesseract")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "${RED}Error: Missing dependencies: ${missing[*]}${NC}"
        echo ""
        echo "Install on macOS with:"
        echo "  brew install ocrmypdf tesseract tesseract-lang"
        echo ""
        echo "Install on Ubuntu/Debian with:"
        echo "  sudo apt install ocrmypdf tesseract-ocr tesseract-ocr-chi-sim"
        exit 1
    fi
}

# Check for Chinese language support
check_chinese() {
    if ! tesseract --list-langs 2>/dev/null | grep -q "chi_sim"; then
        echo -e "${YELLOW}Warning: Chinese (Simplified) language pack not found${NC}"
        echo "Install with: brew install tesseract-lang"
        return 1
    fi
    return 0
}

# Main function
main() {
    local input_pdf="$1"
    local output_pdf="$2"
    local lang="${3:-chi_sim+eng}"

    if [ -z "$input_pdf" ]; then
        echo "Usage: $0 input.pdf [output.pdf] [language]"
        echo ""
        echo "Languages:"
        echo "  chi_sim     - Simplified Chinese"
        echo "  chi_tra     - Traditional Chinese"
        echo "  eng         - English"
        echo "  chi_sim+eng - Chinese + English (default)"
        exit 1
    fi

    if [ ! -f "$input_pdf" ]; then
        echo -e "${RED}Error: Input file not found: $input_pdf${NC}"
        exit 1
    fi

    # Generate output filename if not specified
    if [ -z "$output_pdf" ]; then
        local basename="${input_pdf%.pdf}"
        output_pdf="${basename}_ocr.pdf"
    fi

    check_deps

    # Check if Chinese is needed and available
    if [[ "$lang" == *"chi"* ]]; then
        check_chinese || lang="eng"
    fi

    echo -e "${GREEN}Starting OCR...${NC}"
    echo "  Input:    $input_pdf"
    echo "  Output:   $output_pdf"
    echo "  Language: $lang"
    echo ""

    # Run OCR
    ocrmypdf \
        --language "$lang" \
        --force-ocr \
        --optimize 1 \
        --output-type pdf \
        --jobs 4 \
        "$input_pdf" "$output_pdf"

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}OCR completed successfully!${NC}"
        echo "Output: $output_pdf"

        # Show file sizes
        local input_size=$(du -h "$input_pdf" | cut -f1)
        local output_size=$(du -h "$output_pdf" | cut -f1)
        echo "Size: $input_size -> $output_size"
    else
        echo -e "${RED}OCR failed${NC}"
        exit 1
    fi
}

main "$@"
