/*
  Fingerprint ID allocation:
  - Each user gets assigned IDs based on their email
  - User 1: IDs 0-4 (5 fingerprints)
  - User 2: IDs 5-9 (5 fingerprints)
  - User 3: IDs 10-14 (5 fingerprints)
  - etc.
  
  Example:
  manju@gmail.com → User #0 → IDs 0-4
  doctor@hospital.com → User #1 → IDs 5-9
*/

// Backend: store this mapping in a JSON file or database
{
  "fingerprint_mapping": {
    "manju@gmail.com": {
      "user_id": 0,
      "fingerprint_ids": [0, 1, 2, 3, 4],
      "fingerprint_names": ["Thumb", "Index", "Middle", "Ring", "Pinky"],
      "registered_at": "2026-04-28T15:00:00Z"
    },
    "doctor@hospital.com": {
      "user_id": 1,
      "fingerprint_ids": [5, 6, 7, 8, 9],
      "fingerprint_names": ["Thumb", "Index", "Middle", "Ring", "Pinky"],
      "registered_at": "2026-04-28T14:00:00Z"
    }
  }
}
