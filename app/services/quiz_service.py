from app.core.errors import FeatureNotImplemented


class QuizService:
    def create_question_item(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.create_question_item")

    def create_quiz(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.create_quiz")

    def edit_bank_question(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.edit_bank_question")

    def finalize_expired_attempts(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.finalize_expired_attempts")

    def get_own_quiz_attempt(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.get_own_quiz_attempt")

    def get_question_item(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.get_question_item")

    def get_quiz(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.get_quiz")

    def get_quiz_attempt(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.get_quiz_attempt")

    def get_quiz_result(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.get_quiz_result")

    def list_question_items(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.list_question_items")

    def list_quizzes(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.list_quizzes")

    def publish_quiz(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.publish_quiz")

    def save_answer(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.save_answer")

    def seal(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.seal")

    def start_attempt(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.start_attempt")

    def update_quiz(self, **kwargs: object):
        raise FeatureNotImplemented("QuizService.update_quiz")
