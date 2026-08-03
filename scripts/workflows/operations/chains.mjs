export const STAGE_CHAINS = {
  paper: {
    sequence: ["acquire", "prepare", "analyse", "audit"],
    carries: [
      {
        from: "prepare",
        reads: ["selected_input"],
        apply: (receipt, context) => ({
          ...context,
          input: receipt.selected_input,
        }),
      },
    ],
  },
};
