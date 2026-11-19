// Generates app/tests/fixtures/abs_name_parse.json: how Audiobookshelf itself
// parses author names, so app/abs_names.py (the Python port) can be checked
// against the real thing.
//
// Run inside the Audiobookshelf container, from the repo root:
//   docker exec -i audiobookshelf node - < tools/abs_name_fixture.js > app/tests/fixtures/abs_name_parse.json
//
// Committed fixture produced by Audiobookshelf 2.35.1 (its parseNameString.js
// and parseFullName.js are identical to release v2.37.2). Every name here is
// made up: never add a real author.
const fs = require('fs')
const parseFullName = require('/app/server/utils/parsers/parseFullName.js')
const parseNameString = require('/app/server/utils/parsers/parseNameString.js')

const fullNames = [
  // 1 to 5 words
  'Quillon', 'author103', 'Ana Pell', 'Mara J. Holt', 'Ivo Ren Sand', 'Lee Ann Mae Doan', 'Pia Ro Lu Mae Kest',
  // initials
  'A.B. Carver', 'A B Carver', 'A. B. Carver', 'JK Varn', 'J.K.Varn', 'Kevin J Orrin', 'A.B.C. Dunmore',
  // particles
  'Mira van der Holt', 'Jon Le Brun', 'Ana de la Vega', 'Otto von Barl', 'Lia di Sarno', 'Pim van Doorn',
  // suffixes and titles
  'Tomas Reed Jr.', 'Tomas Reed III', 'Tomas Reed, Jr.', 'Dr. Ilse Varn', 'Prof. Hal Grend',
  // case fixing (all lower / all upper input)
  'ana pell', 'ANA PELL', 'mara mcvane', 'jon le brun', 'tomas reed iii',
  // nickname, conjunction, extra commas, last-first
  'Hal "Ace" Grend', 'Ana and Ivo Pell', 'Holt, Mara', 'Holt, Mara J.', 'Reed, Tomas, Jr., Esq.',
  // non-Latin
  '林小雨', 'Søren Kjær',
  // odd shapes
  '', '  Ana   Pell  ', 'Mara-Lin Holt', "Ilse O'Varn",
]

const nameStrings = [
  'Ana Pell',
  'Quillon',
  'Holt, Mara',
  'Ana Pell, Ivo Sand',
  'Ana Pell, Ivo Sand, Lee Doan',
  'Ana Pell, Ivo Sand & Lee Doan',
  'Ana Pell, Ivo Sand, & Lee Doan',
  'Ana Pell, Ivo Sand and Lee Doan',
  'Ana Pell, Ivo Sand, and Lee Doan',
  'Ana Pell & Ivo Sand',
  'Ana Pell and Ivo Sand',
  'Ana Pell & Ivo Sand & Lee Doan',
  'Ana Pell; Ivo Sand; Lee Doan',
  'Ana Pell; Ivo Sand & Lee Doan',
  'Ana Pell; Ivo Sand and Lee Doan',
  'Ana Pell & Ivo Sand and Lee Doan',
  'Ana Pell - Ivo Sand and Lee Doan',
  'Ana Pell with Ivo Sand',
  'Ana Pell And Ivo Sand',
  'Pell, Ana, Sand, Ivo',
  'Pell, Ana & Sand, Ivo',
  'Pell, Ana, Sand, Ivo, Doan, Lee',
  'Pell, Ana; Sand, Ivo',
  'Holt, Mara J., Sand, Ivo & Le Brun, Jon',
  'J. Holt, Mara, Ren Sand, Ivo & Le Brun, Jon',
  'Pell, Ana, Sand, Ivo, Doan',
  'Quillon, Ivo Sand',
  'Quillon & Ivo Sand',
  'author103, Ivo Sand',
  'Quillon, Pell, Sand',
  'Quillon & Pell & Sand',
  'Mira van der Holt, Jon Le Brun',
  'van der Holt, Mira, Le Brun, Jon',
  'Tomas Reed Jr., Ivo Sand',
  'Tomas Reed Jr. & Ivo Sand',
  'Dr. Ilse Varn & Ivo Sand',
  'A.B. Carver & Ivo Sand',
  'A.B. Carver, Ivo Sand',
  'Carver, A.B. & Sand, Ivo',
  'JK Varn & Ana Pell',
  'Ana Pell, Ivo Sand, Lee Doan, Mara Holt',
  'Ana Pell, Ivo Sand, Lee Doan, Mara Holt and et al',
  'Ana Pell, Ivo Sand, Lee Doan, Mara Holt, & et al',
  'Ana Pell & Ivo Sand & Lee Doan & Mara Holt & et al',
  'Ana Pell; Ivo Sand; Lee Doan; Mara Holt; et al',
  'Ana Pell et al',
  'Ana Pell & others',
  'Ana Pell, Ivo Sand, and others',
  'Ana Pell & Ana Pell',
  'Ana Pell, Ana Pell',
  'Ana Pell & ',
  '林小雨, 王小明',
  '林小雨 & 王小明',
  'ana pell & ivo sand',
  'Holt, & Sand, Ivo',
  'Pell-Rowe, Ana & Sand, Ivo',
]

const out = { abs_version: require('/app/package.json').version, full_names: {}, name_strings: {} }
for (const name of fullNames) {
  const parsed = parseFullName(name)
  delete parsed.error
  out.full_names[name] = parsed
}
for (const value of nameStrings) {
  const parsed = parseNameString.parse(value)
  out.name_strings[value] = parsed ? parsed.names : []
}
fs.writeSync(1, JSON.stringify(out, null, 2) + '\n')
