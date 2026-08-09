class DomainException(Exception):
    """Base domain exception."""
    pass

class LLMGenerationError(DomainException):
    """Raised when LLM model fails to generate code."""
    pass

class GitRepositoryError(DomainException):
    """Raised when git or pull request operations fail."""
    pass
