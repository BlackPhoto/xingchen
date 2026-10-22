"""
Validator for Word document XML files against XSD schemas.
"""

import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass

import lxml.etree

from .base_workflow import base_schema_validator_impl


def needs_xml_space_preserve_impl(text):
    """Return whether OOXML text starts or ends with XML-defined whitespace."""
    return bool(text) and (text[0] in " \t\r\n" or text[-1] in " \t\r\n")


@dataclass(frozen=True)
class whitespace_violation_impl:
    """A whitespace violation with a stable-enough identity for baseline matching."""

    part: str
    paragraph_anchor: tuple
    text_index: int
    text: str
    line: int

    @property
    def identity(self):
        return (self.part, self.paragraph_anchor, self.text_index, self.text)

    def __str__(self):
        text_preview = repr(self.text)
        if len(text_preview) > 50:
            text_preview = text_preview[:50] + "..."
        return (
            f"  {self.part}: Line {self.line}: w:t element with whitespace "
            f"missing xml:space='preserve': {text_preview}"
        )


class docx_schema_validator_impl(base_schema_validator_impl):
    """Validator for Word document XML files against XSD schemas."""

    # Word-specific namespace
    WORD_2006_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    WORD_2010_NAMESPACE = "http://schemas.microsoft.com/office/word/2010/wordml"

    # Word-specific element to relationship type mappings
    # Start with empty mapping - add specific cases as we discover them
    ELEMENT_RELATIONSHIP_TYPES = {}

    def validate_impl(self):
        """Run all validation checks and return True if all pass."""
        # Test 0: XML well-formedness
        if not self.validate_xml_impl():
            return False

        # Test 1: Namespace declarations
        all_valid = True
        if not self.validate_namespaces_impl():
            all_valid = False

        # Test 2: Unique IDs
        if not self.validate_unique_ids_impl():
            all_valid = False

        # Test 3: Relationship and file reference validation
        if not self.validate_file_references_impl():
            all_valid = False

        # Test 4: Content type declarations
        if not self.validate_content_types_impl():
            all_valid = False

        # Test 5: XSD schema validation
        if not self.validate_against_xsd_impl():
            all_valid = False

        # Test 6: Whitespace preservation
        if not self.validate_whitespace_preservation_impl():
            all_valid = False

        # Test 7: Deletion validation
        if not self.validate_deletions_impl():
            all_valid = False

        # Test 8: Insertion validation
        if not self.validate_insertions_impl():
            all_valid = False

        # Test 9: Relationship ID reference validation
        if not self.validate_all_relationship_ids_impl():
            all_valid = False

        # Count and compare paragraphs
        self.compare_paragraph_counts_impl()

        return all_valid

    def _paragraph_anchor(self, paragraphs, paragraph_index):
        """Build an anchor that survives unrelated paragraph insertions when possible."""
        paragraph = paragraphs[paragraph_index]
        para_id = paragraph.get(f"{{{self.WORD_2010_NAMESPACE}}}paraId")
        if para_id:
            return ("paraId", para_id)

        def paragraph_text(index):
            if index < 0 or index >= len(paragraphs):
                return None
            return "".join(
                elem.text or ""
                for elem in paragraphs[index].iter(
                    f"{{{self.WORD_2006_NAMESPACE}}}t"
                )
            )

        # Older documents may not have w14:paraId. Text plus immediate context
        # is deliberately conservative: if an edit makes identity ambiguous,
        # validation treats the violation as new and asks for review.
        return (
            "context",
            paragraph_text(paragraph_index),
            paragraph_text(paragraph_index - 1),
            paragraph_text(paragraph_index + 1),
        )

    def collect_whitespace_violations(self):
        """
        Collect w:t elements whose text may lose whitespace without
        xml:space='preserve'.

        Only XML-defined whitespace (space, tab, CR, LF) is checked. Unicode
        whitespace such as U+3000 (ideographic space) is never stripped by
        conforming XML processors regardless of xml:space, so it is
        intentionally not treated as a violation.

        Returns:
            list[whitespace_violation_impl]: Structured violation records.
        """
        errors = []

        for xml_file in self.xml_files:
            # Only check document.xml files
            if xml_file.name != "document.xml":
                continue

            try:
                root = lxml.etree.parse(str(xml_file)).getroot()

                paragraphs = list(
                    root.iter(f"{{{self.WORD_2006_NAMESPACE}}}p")
                )
                for paragraph_index, paragraph in enumerate(paragraphs):
                    text_elements = list(
                        paragraph.iter(f"{{{self.WORD_2006_NAMESPACE}}}t")
                    )
                    paragraph_anchor = self._paragraph_anchor(
                        paragraphs, paragraph_index
                    )
                    for text_index, elem in enumerate(text_elements):
                        if not elem.text:
                            continue
                        text = elem.text
                        # Check if text starts or ends with XML whitespace
                        # (do NOT use \s: it also matches Unicode whitespace
                        # like U+3000, which requires no xml:space attribute)
                        if needs_xml_space_preserve_impl(text):
                            # Check if xml:space="preserve" attribute exists
                            xml_space_attr = f"{{{self.XML_NAMESPACE}}}space"
                            if (
                                xml_space_attr not in elem.attrib
                                or elem.attrib[xml_space_attr] != "preserve"
                            ):
                                errors.append(
                                    whitespace_violation_impl(
                                        part=str(
                                            xml_file.relative_to(self.unpacked_dir)
                                        ),
                                        paragraph_anchor=paragraph_anchor,
                                        text_index=text_index,
                                        text=text,
                                        line=elem.sourceline or 0,
                                    )
                                )

            except (lxml.etree.XMLSyntaxError, OSError):
                # XML well-formedness is reported by validate_xml_impl(). Avoid
                # turning parser errors into baseline-able whitespace issues.
                continue

        return errors

    # Structured violations from the pristine unpacked content. Set by
    # document_impl before edits are made. A tuple keeps the class default
    # immutable for validators used outside document_impl.
    baseline_whitespace_violations = ()

    def partition_whitespace_violations(self, errors):
        """Split current violations into pre-existing and unmatched ones."""
        baseline = Counter(
            violation.identity
            for violation in self.baseline_whitespace_violations
        )
        pre_existing = []
        unmatched = []
        for error in errors:
            if baseline[error.identity] > 0:
                baseline[error.identity] -= 1
                pre_existing.append(error)
            else:
                unmatched.append(error)
        return pre_existing, unmatched

    def validate_whitespace_preservation_impl(self):
        """
        Validate that w:t elements with whitespace have xml:space='preserve'.

        Violations that match the pre-edit baseline are reported as warnings
        and do not fail validation. New, changed, or otherwise unmatched
        violations cause a failure so an agent can review them.
        """
        errors = self.collect_whitespace_violations()
        pre_existing, unmatched = self.partition_whitespace_violations(errors)

        if unmatched:
            print(
                f"FAILED - Found {len(unmatched)} new or changed whitespace "
                f"preservation violation(s) ({len(errors)} total):"
            )
            for error in unmatched:
                print(error)
            if pre_existing:
                print(
                    f"WARNING - {len(pre_existing)} pre-existing whitespace "
                    "preservation violation(s) ignored:"
                )
                for error in pre_existing:
                    print(error)
            return False

        if pre_existing:
            print(
                f"PASSED - {len(pre_existing)} pre-existing whitespace preservation "
                "violation(s) ignored; no new violations introduced:"
            )
            for error in pre_existing:
                print(error)
        elif self.verbose:
            print("PASSED - All whitespace is properly preserved")
        return True

    def validate_deletions_impl(self):
        """
        Validate that w:t elements are not within w:del elements.
        For some reason, XSD validation does not catch this, so we do it manually.
        """
        errors = []

        for xml_file in self.xml_files:
            # Only check document.xml files
            if xml_file.name != "document.xml":
                continue

            try:
                root = lxml.etree.parse(str(xml_file)).getroot()

                # Find all w:t elements that are descendants of w:del elements
                namespaces = {"w": self.WORD_2006_NAMESPACE}
                xpath_expression = ".//w:del//w:t"
                problematic_t_elements = root.xpath(
                    xpath_expression, namespaces=namespaces
                )
                for t_elem in problematic_t_elements:
                    if t_elem.text:
                        # Show a preview of the text
                        text_preview = (
                            repr(t_elem.text)[:50] + "..."
                            if len(repr(t_elem.text)) > 50
                            else repr(t_elem.text)
                        )
                        errors.append(
                            f"  {xml_file.relative_to(self.unpacked_dir)}: "
                            f"Line {t_elem.sourceline}: <w:t> found within <w:del>: {text_preview}"
                        )

            except (lxml.etree.XMLSyntaxError, Exception) as e:
                errors.append(
                    f"  {xml_file.relative_to(self.unpacked_dir)}: Error: {e}"
                )

        if errors:
            print(f"FAILED - Found {len(errors)} deletion validation violations:")
            for error in errors:
                print(error)
            return False
        else:
            if self.verbose:
                print("PASSED - No w:t elements found within w:del elements")
            return True

    def count_paragraphs_in_unpacked_impl(self):
        """Count the number of paragraphs in the unpacked document."""
        count = 0

        for xml_file in self.xml_files:
            # Only check document.xml files
            if xml_file.name != "document.xml":
                continue

            try:
                root = lxml.etree.parse(str(xml_file)).getroot()
                # Count all w:p elements
                paragraphs = root.findall(f".//{{{self.WORD_2006_NAMESPACE}}}p")
                count = len(paragraphs)
            except Exception as e:
                print(f"Error counting paragraphs in unpacked document: {e}")

        return count

    def count_paragraphs_in_original_impl(self):
        """Count the number of paragraphs in the original docx file."""
        count = 0

        try:
            # Create temporary directory to unpack original
            with tempfile.TemporaryDirectory() as temp_dir:
                # Unpack original docx
                with zipfile.ZipFile(self.original_file, "r") as zip_ref:
                    zip_ref.extractall(temp_dir)

                # Parse document.xml
                doc_xml_path = temp_dir + "/word/document.xml"
                root = lxml.etree.parse(doc_xml_path).getroot()

                # Count all w:p elements
                paragraphs = root.findall(f".//{{{self.WORD_2006_NAMESPACE}}}p")
                count = len(paragraphs)

        except Exception as e:
            print(f"Error counting paragraphs in original document: {e}")

        return count

    def validate_insertions_impl(self):
        """
        Validate that w:delText elements are not within w:ins elements.
        w:delText is only allowed in w:ins if nested within a w:del.
        """
        errors = []

        for xml_file in self.xml_files:
            if xml_file.name != "document.xml":
                continue

            try:
                root = lxml.etree.parse(str(xml_file)).getroot()
                namespaces = {"w": self.WORD_2006_NAMESPACE}

                # Find w:delText in w:ins that are NOT within w:del
                invalid_elements = root.xpath(
                    ".//w:ins//w:delText[not(ancestor::w:del)]",
                    namespaces=namespaces
                )

                for elem in invalid_elements:
                    text_preview = (
                        repr(elem.text or "")[:50] + "..."
                        if len(repr(elem.text or "")) > 50
                        else repr(elem.text or "")
                    )
                    errors.append(
                        f"  {xml_file.relative_to(self.unpacked_dir)}: "
                        f"Line {elem.sourceline}: <w:delText> within <w:ins>: {text_preview}"
                    )

            except (lxml.etree.XMLSyntaxError, Exception) as e:
                errors.append(
                    f"  {xml_file.relative_to(self.unpacked_dir)}: Error: {e}"
                )

        if errors:
            print(f"FAILED - Found {len(errors)} insertion validation violations:")
            for error in errors:
                print(error)
            return False
        else:
            if self.verbose:
                print("PASSED - No w:delText elements within w:ins elements")
            return True

    def compare_paragraph_counts_impl(self):
        """Compare paragraph counts between original and new document."""
        original_count = self.count_paragraphs_in_original_impl()
        new_count = self.count_paragraphs_in_unpacked_impl()

        diff = new_count - original_count
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        print(f"\nParagraphs: {original_count} → {new_count} ({diff_str})")


if __name__ == "__main__":
    raise RuntimeError("This module should not be run directly.")
