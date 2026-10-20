export const CONSISTENT = "Consistent"
export const FLAGGED = "Flagged for Review"
export const LOW_LESION = "Review - Low Lesion Evidence"
export const CLASSIFIER_ONLY = "Classifier only"

export function isReviewItem(status: string): boolean {
  return status === FLAGGED || status === LOW_LESION
}

export type BadgeTone = "accent" | "destructive" | "success" | "warning"

export function findingBadgeTone(status: string): BadgeTone {
  if (status === FLAGGED) return "destructive"
  if (status === LOW_LESION) return "warning"
  if (status === CONSISTENT) return "success"
  return "accent"
}