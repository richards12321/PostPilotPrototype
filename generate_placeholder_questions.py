"""Generate placeholder question banks for Layer 1.

Run once to create logical.xlsx, numerical.xlsx, verbal.xlsx in data/questions/.
Safe to re-run; it will overwrite.
"""

from pathlib import Path

import pandas as pd

OUT = Path(__file__).parent / "data" / "questions"
OUT.mkdir(parents=True, exist_ok=True)


LOGICAL = [
    ("LG1", "All roses are flowers. Some flowers fade quickly. Therefore:",
     "All roses fade quickly", "Some roses may fade quickly",
     "No roses fade quickly", "Flowers are roses", "B"),
    ("LG2", "If A > B and B > C, which statement must be true?",
     "C > A", "A = C", "A > C", "Cannot be determined", "C"),
    ("LG3", "A father is three times as old as his son. In 12 years, he will be twice as old. How old is the son now?",
     "10", "12", "14", "16", "B"),
    ("LG4", "Which number does not belong? 4, 9, 16, 23, 25",
     "4", "9", "23", "25", "C"),
    ("LG5", "All accountants are careful. Maria is careful. Therefore:",
     "Maria is an accountant", "Maria may or may not be an accountant",
     "Maria is not an accountant", "All careful people are accountants", "B"),
    ("LG6", "In a race of 5 people, Alex finished before Ben but after Carla. Dan finished after Ben. Who finished first?",
     "Alex", "Ben", "Carla", "Dan", "C"),
    ("LG7", "If some managers are engineers, and all engineers are problem-solvers, which must be true?",
     "All managers are problem-solvers", "Some managers are problem-solvers",
     "No managers are problem-solvers", "All problem-solvers are managers", "B"),
    ("LG8", "Complete the sequence: 2, 6, 12, 20, 30, ?",
     "40", "42", "44", "36", "B"),
    ("LG9", "5 people can finish a job in 10 days. How many people are needed to finish the same job in 2 days?",
     "20", "25", "30", "50", "B"),
    ("LG10", "Which conclusion follows from: No consultants work on weekends. Lisa works on weekends.",
     "Lisa is a consultant", "Lisa is not a consultant",
     "Lisa works half days", "Cannot be determined", "B"),
    ("LG11", "If P implies Q, and Q is false, what can we say about P?",
     "P is true", "P is false", "P is uncertain", "P and Q are equivalent", "B"),
    ("LG12", "A clock shows 3:15. What is the angle between the hour and minute hands?",
     "0°", "7.5°", "15°", "22.5°", "B"),
    ("LG13", "Six people sit around a round table. In how many distinct ways can they be arranged (rotations considered the same)?",
     "120", "60", "720", "24", "A"),
    ("LG14", "If today is Wednesday, what day will it be 100 days from now?",
     "Friday", "Saturday", "Sunday", "Monday", "A"),
    ("LG15", "A is the mother of B. B is the brother of C. C is the daughter of D. What is A to D?",
     "Sister", "Wife", "Daughter", "Cannot be determined", "B"),
    ("LG16", "Complete the analogy: Book is to Reading as Fork is to:",
     "Drawing", "Writing", "Eating", "Cooking", "C"),
    ("LG17", "If all Bloops are Razzies, and some Razzies are Lazzies, then:",
     "Some Bloops are definitely Lazzies", "All Lazzies are Bloops",
     "Some Bloops may be Lazzies", "No Bloops are Lazzies", "C"),
    ("LG18", "Four friends sit in a row. Ana is not at the ends. Ben is next to Ana. Carla is at one end. Where can Dan sit?",
     "Only the other end", "Next to Ben only",
     "Between Ana and Ben", "Either end", "A"),
    ("LG19", "Which statement is the contrapositive of 'If it rains, the ground is wet'?",
     "If the ground is wet, it rains", "If it does not rain, the ground is not wet",
     "If the ground is not wet, it does not rain", "The ground is wet only when it rains", "C"),
    ("LG20", "A store offers 20% off, then another 10% off the reduced price. What is the total discount?",
     "30%", "28%", "25%", "32%", "B"),
]


NUMERICAL = [
    ("NA1", "A company's revenue grew from €40M to €52M. What is the percentage growth?",
     "25%", "30%", "35%", "20%", "B"),
    ("NA2", "If the cost is €80 and markup is 25%, what is the selling price?",
     "€100", "€105", "€110", "€95", "A"),
    ("NA3", "A project budget is €500,000. 60% is spent on staff, 25% on travel, and the rest on materials. How much on materials?",
     "€50,000", "€75,000", "€100,000", "€125,000", "B"),
    ("NA4", "A stock price rises 20%, then falls 20%. Net change?",
     "0%", "−4%", "+4%", "−2%", "B"),
    ("NA5", "If 15 workers build a wall in 20 days, how many workers are needed to build it in 12 days?",
     "20", "25", "30", "18", "B"),
    ("NA6", "A car travels 180 km in 3 hours, then 120 km in 2 hours. Average speed?",
     "55 km/h", "60 km/h", "65 km/h", "50 km/h", "B"),
    ("NA7", "Simple interest on €5,000 at 6% per year for 3 years?",
     "€800", "€900", "€1,000", "€1,100", "B"),
    ("NA8", "A firm's gross margin is 40%. If revenue is €2M, what is the cost of goods sold?",
     "€800,000", "€1,000,000", "€1,200,000", "€1,400,000", "C"),
    ("NA9", "Convert 7/20 to a percentage.",
     "30%", "35%", "40%", "28%", "B"),
    ("NA10", "If a = 3 and b = 5, compute a² + 2ab + b².",
     "49", "64", "56", "72", "B"),
    ("NA11", "A product is discounted 15% and now costs €68. What was the original price?",
     "€75", "€78.20", "€80", "€85", "C"),
    ("NA12", "The ratio of men to women in an office is 3:5. If there are 64 people total, how many women?",
     "24", "32", "40", "48", "C"),
    ("NA13", "A rectangle has length 12 and width 5. What is its area?",
     "50", "55", "60", "65", "C"),
    ("NA14", "If EBITDA is €500,000 and revenue is €2.5M, what is the EBITDA margin?",
     "15%", "18%", "20%", "25%", "C"),
    ("NA15", "Revenue forecast for Q3: €1.2M, Q4: €1.5M. What is the quarter-over-quarter growth?",
     "20%", "25%", "30%", "15%", "B"),
    ("NA16", "A consultant bills 1,600 hours per year at €250/hour. Annual billings?",
     "€350,000", "€400,000", "€450,000", "€500,000", "B"),
    ("NA17", "If a stock pays a €2 dividend and the share price is €40, what is the dividend yield?",
     "3%", "4%", "5%", "6%", "C"),
    ("NA18", "A project takes 45 days and finishes 9 days early. What percentage of the original schedule was saved?",
     "15%", "20%", "25%", "30%", "B"),
    ("NA19", "Currency conversion: €100 = $110. If you have $550, how many euros?",
     "€450", "€500", "€550", "€475", "B"),
    ("NA20", "Net profit is €120,000 on revenue of €800,000. Net margin?",
     "12%", "15%", "18%", "20%", "B"),
]


VERBAL = [
    ("VB1", "Choose the word closest in meaning to 'mitigate':",
     "Enhance", "Alleviate", "Accelerate", "Postpone", "B"),
    ("VB2", "Which word is the opposite of 'succinct'?",
     "Brief", "Verbose", "Clear", "Direct", "B"),
    ("VB3", "Complete the sentence: Despite being _____ in resources, the team delivered on time.",
     "abundant", "constrained", "plentiful", "excessive", "B"),
    ("VB4", "Passage: 'The firm's quarterly results exceeded expectations, driven largely by cost reductions rather than revenue growth.' Which conclusion is best supported?",
     "Revenue growth drove the results", "Cost discipline outperformed top-line expansion",
     "The firm is struggling overall", "Revenue declined this quarter", "B"),
    ("VB5", "Identify the grammatical error: 'Neither the manager nor the consultants was available.'",
     "Neither/nor usage", "Verb agreement with nearest subject",
     "Missing comma", "No error", "B"),
    ("VB6", "Which statement is an opinion, not a fact?",
     "The report was published in June", "The strategy is the best option",
     "Revenue increased by 10%", "The meeting lasted an hour", "B"),
    ("VB7", "Choose the best synonym for 'ubiquitous':",
     "Rare", "Widespread", "Complicated", "Traditional", "B"),
    ("VB8", "Which word best completes the sentence? 'The CEO's remarks were deliberately ______, leaving analysts uncertain.'",
     "explicit", "ambiguous", "redundant", "obvious", "B"),
    ("VB9", "Passage: 'While some employees embraced the new system, others remained skeptical.' What does this suggest?",
     "All employees loved the system", "Reception was mixed",
     "The system failed", "Employees were indifferent", "B"),
    ("VB10", "Which sentence uses the semicolon correctly?",
     "The meeting ended; everyone left satisfied.", "The meeting ended, everyone; left satisfied.",
     "The meeting; ended everyone left satisfied.", "The meeting ended everyone left; satisfied.", "A"),
    ("VB11", "Choose the word closest in meaning to 'scrutinize':",
     "Ignore", "Examine closely", "Delegate", "Dismiss", "B"),
    ("VB12", "Which is an example of faulty reasoning?",
     "Correlation implies causation", "Citing multiple sources",
     "Using statistical evidence", "Defining terms clearly", "A"),
    ("VB13", "The phrase 'bite the bullet' means:",
     "Eat quickly", "Accept something unpleasant",
     "Speak harshly", "Save money", "B"),
    ("VB14", "Pick the word that does not belong:",
     "Verify", "Confirm", "Validate", "Assume", "D"),
    ("VB15", "Which conclusion follows from: 'Most startups fail within five years. InnoCo is a startup.'?",
     "InnoCo will fail", "InnoCo is likely to fail within five years",
     "InnoCo will succeed", "Startups always fail", "B"),
    ("VB16", "'The proposal was met with tepid enthusiasm.' What does 'tepid' mean here?",
     "Overwhelming", "Lukewarm", "Hostile", "Cautious optimism", "B"),
    ("VB17", "Which is the main idea of this sentence: 'Although the methodology was sound, the conclusions lacked supporting data.'?",
     "The methodology was flawed", "Conclusions were well supported",
     "Good method, insufficient evidence", "The study was rejected", "C"),
    ("VB18", "'Parsimonious' most nearly means:",
     "Extravagant", "Frugal", "Generous", "Wasteful", "B"),
    ("VB19", "Which sentence is most concise without losing meaning?",
     "Due to the fact that the project was delayed, we missed the deadline.",
     "Because the project was delayed, we missed the deadline.",
     "The project being delayed was the reason we missed the deadline.",
     "The reason for missing the deadline was that the project was delayed.", "B"),
    ("VB20", "The idiom 'playing devil's advocate' means:",
     "Supporting evil", "Arguing a position for the sake of debate",
     "Refusing to take sides", "Being dishonest", "B"),
]


def write(name: str, rows: list) -> None:
    df = pd.DataFrame(rows, columns=[
        "question_id", "question_text", "option_a", "option_b",
        "option_c", "option_d", "correct_answer",
    ])
    path = OUT / f"{name}.xlsx"
    df.to_excel(path, index=False)
    print(f"Wrote {path} ({len(df)} questions)")


if __name__ == "__main__":
    write("logical", LOGICAL)
    write("numerical", NUMERICAL)
    write("verbal", VERBAL)
