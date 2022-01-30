import argparse
from collections import defaultdict
from locale import normalize
from math import inf
from dataclasses import dataclass, field
from enum import Enum
from random import choice, sample, shuffle
import re
from sys import stderr
from typing import Optional
import unicodedata
from unittest import result
from pyparsing import NoMatch
from termcolor import colored
from string import ascii_uppercase

def normalize(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s.upper())
                   if unicodedata.category(c) != 'Mn')

class MatchStatus(Enum):
    NO_MATCH = 0
    WRONG_POSITION = 1
    CORRECT_POSITION = 2

@dataclass
class GuessResult:
    word: str
    result: list[MatchStatus]

    def __bool__(self):
        return all([match_status == MatchStatus.CORRECT_POSITION for match_status in self.result])

    def __str__(self) -> str:
      ret = ""
      colors = {
        MatchStatus.NO_MATCH: 'red',
        MatchStatus.WRONG_POSITION: 'yellow',
        MatchStatus.CORRECT_POSITION: 'green',
      }
      return "".join([ 
        colored(char, colors[match_status])
        for char, match_status in zip(self.word, self.result)
      ])




@dataclass
class CharInfo:
    char: str
    correct_positions: set[int] = field(default_factory=set)
    wrong_positions: set[int] = field(default_factory=set)
    min_amount: int = 0
    max_amount: int = inf

    def match(self, word):
        for i in self.correct_positions:
            if word[i] != self.char:
                return False
        for i in self.wrong_positions:
            if word[i] == self.char:
                return False
        count = word.count(self.char)
        if count < self.min_amount or count > self.max_amount:
            return False
        return True

    def add(self, match_count: int, has_mismatches: bool, correct_positions: set[int], wrong_positions: set[int]) -> "CharInfo":
        correct_positions = self.correct_positions if correct_positions is None else self.correct_positions | correct_positions
        wrong_positions = self.wrong_positions if wrong_positions is None else self.wrong_positions | wrong_positions
        return CharInfo(
            char = self.char,
            correct_positions = correct_positions,
            wrong_positions = wrong_positions,
            min_amount = max(self.min_amount, match_count, len(correct_positions)),
            max_amount = match_count if has_mismatches else self.max_amount,
        )


@dataclass
class AllInfo:
    char_info: dict[str, CharInfo] = field(default_factory=lambda: {
      char: CharInfo(char)
      for char in ascii_uppercase
    })

    def match(self, word) -> bool:
      word = normalize(word)
      for char in self.char_info.values():
        if not char.match(word):
          return False
      return True

    def filter(self, words: set[str]) -> set[str]:
      return set(filter(self.match, words))

    def __add__(self, guess_result: GuessResult) -> "AllInfo":
      word_size = len(guess_result.word)
      char_match_count = defaultdict(int)
      char_mismatches: set[str] = set()
      char_correct_positions = defaultdict(set)
      char_wrong_positions = defaultdict(set)

      for i, (char, result) in enumerate(zip(normalize(guess_result.word), guess_result.result)):
          if result == MatchStatus.NO_MATCH:
              char_mismatches.add(char)
              char_wrong_positions[char].add(i)
          else:
              char_match_count[char] += 1
              if result == MatchStatus.CORRECT_POSITION:
                  char_correct_positions[char].add(i)
              else:
                  char_wrong_positions[char].add(i)

      ret = AllInfo(
          char_info = {
            char: info.add(char_match_count.get(char, 0), char in char_mismatches, char_correct_positions.get(char), char_wrong_positions.get(char))
            for char, info in self.char_info.items()
          }
      )
      known_char_count = sum(info.min_amount for info in ret.char_info.values())
      unknown_char_count = word_size - known_char_count
      for char_info in ret.char_info.values():
        char_info.max_amount = min(char_info.max_amount, char_info.min_amount + unknown_char_count, word_size - len(char_info.wrong_positions))

      return ret

class Game:
    def __init__(self, words: set[str], secret_word: Optional[str] = None):
        self.secret_word = secret_word
        self.all_info = AllInfo()
        self.word_size = len(next(iter(words)))
        self.words = words
        self.possible_words = words

    def merge_result(self, guess_result: GuessResult):
        self.all_info += guess_result
        self.possible_words = self.all_info.filter(self.possible_words)

    def automatic_guess(self) -> str:
        if len(self.possible_words) == 1:
            return next(iter(self.possible_words))  # Knows the answer
        elif len(self.possible_words) == 0:
            return None  # Give up, doesn't know the word

        # Look into the vocabulary for the word that is likely to reduces the possible_words the most
        letter_pos_prob = {
          char: [0] * (self.word_size + 1)
          for char in ascii_uppercase
        }
        letter_count_prob = {
          char: [0] * (self.word_size + 1)
          for char in ascii_uppercase
        }
        for word in self.possible_words:
            word_normalized = normalize(word)
            for i, char in enumerate(word_normalized):
                letter_pos_prob[char][i] += 1
            for char in ascii_uppercase:
                letter_count_prob[char][word_normalized.count(char)] += 1
        
        for char in ascii_uppercase:
            for i in range(self.word_size + 1):
                letter_pos_prob[char][i] /= len(self.words)
                letter_count_prob[char][i] /= len(self.words)

        best_guess = None
        best_score = inf
        for word in self.words:
            score = 1
            char_count = defaultdict(int)
            for i, char in enumerate(normalize(word)):
                char_count[char] += 1
                count = char_count[char]

                p_correct = letter_pos_prob[char][i]
                p_pos = max(sum(letter_count_prob[char][count:]) - p_correct, 0)
                p_wrong = sum(letter_count_prob[char][:count])

                score *= max(p_correct, p_pos, p_wrong)  # p_correct * p_correct + p_pos * p_pos + p_wrong * p_wrong
            if score < best_score:
                best_score = score
                best_guess = word
        return best_guess

    def automatic_check(self, guess: str) -> GuessResult:
        answer_normalized = normalize(self.secret_word)
        guess_normalized = normalize(guess)

        actual_letters = list(answer_normalized)
        size = len(actual_letters)
        result = [None] * size

        # Search for exact match
        for i in range(size):
            if guess_normalized[i] == actual_letters[i]:
                result[i] = MatchStatus.CORRECT_POSITION
                actual_letters[i] = None

        # Search for wrong position match
        for i in range(size):
            if result[i] is None:
                for j in range(size):
                  if guess_normalized[i] == actual_letters[j]:
                      result[i] = MatchStatus.WRONG_POSITION
                      actual_letters[j] = None
                      break
                if result[i] is None:
                    result[i] = MatchStatus.NO_MATCH

        return GuessResult(guess, result)
        

class Main:
    def __init__(self, words_file: argparse.FileType) -> None:
        with words_file:
            words = sorted(re.findall(r'\w+', words_file.read().upper()))

        self.normalized_words = {
            normalize(word): word
            for word in words
        }
        self.words = list(self.normalized_words.values())

    def shuffled_words(self):
        while True:
            yield choice(self.words)

    def user_guess(self) -> str:
        while True:
            text = input("Next guess: ")
            try:
                guess = self.normalized_words.get(normalize(text))
                if guess is not None:
                    return guess
            except:
                pass

            print("Invalid word", file=stderr)

    def user_check(self, guess: str) -> GuessResult:
        while True:
            text = input(f"Result for '{guess}': ")
            try:
                results = [
                    MatchStatus(int(x))
                    for x in text
                ]
                if len(results) == len(guess):
                    return GuessResult(guess, results)
            except:
                pass

            print("Invalid result", file=stderr)

    def game_loop(self, user_guess, user_check, hints=0):
        if user_check:
            print("For each letter, enter `0` if it doesn't exist in the word, `1` if it is in the wrong position and `2` if it is correct")
            print()

        for game_num, secret_word in enumerate(self.shuffled_words()):
            if user_check: 
                secret_word = "<?>"
            print(f"Game #{game_num + 1}: {secret_word}")
            game = Game(self.words, secret_word)

            num_guesses = 0
            while True:
                if hints:
                    max_hints = 10
                    samples = sorted(sample(list(game.possible_words), min(max_hints, len(game.possible_words))))
                    hint_str = (', '.join(samples)) + (", ..." if len(game.possible_words) > max_hints else "")
                    print(f"Hint: {len(game.possible_words)} possible words: {hint_str}")

                if user_guess:
                    guess = self.user_guess()
                else:
                    guess = game.automatic_guess()
                
                if guess is None:
                    print(colored("Giving up on this word!", "red"))
                    break

                num_guesses += 1

                if user_check:
                    guess_result = self.user_check(guess)
                else:
                    guess_result = game.automatic_check(guess)

                game.merge_result(guess_result)
                print(f"#{num_guesses}: {guess_result}")

                if guess_result:
                    break  # Game completed!

            print()
            print()


def cli_main():
    parser = argparse.ArgumentParser(description='Wordle solver')
    parser.add_argument('--words', '-w', metavar='WORDS.TXT', 
        type=argparse.FileType('r'), 
        required=True,
        help='File containing the vocabulary of known words')

    parser.add_argument('--guess', action='store_true', 
                        help='Guessing is performed by the iteractive user')
    parser.add_argument('--check', action='store_true', 
                        help='Check is performed by iteractive user')
    parser.add_argument('--hints', action='store_true', 
                        help='Shows hints of possible words')

    args = parser.parse_args()
    Main(args.words).game_loop(args.guess, args.check, args.hints)


cli_main()
