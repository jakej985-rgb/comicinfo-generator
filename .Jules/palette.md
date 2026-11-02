## 2024-11-02 - Added focus visible outlines to inputs and interactive elements
**Learning:** Found that many custom focus states were missing or only setting border colors on inputs, which is poor for accessibility navigation. Also, icon-only buttons lacked aria labels.
**Action:** Always add aria-labels to buttons where text is absent. Enhance focus styles using focus-visible for better keyboard navigation.
