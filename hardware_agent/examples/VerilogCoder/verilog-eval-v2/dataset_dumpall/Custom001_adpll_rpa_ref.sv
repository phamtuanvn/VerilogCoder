// Reference implementation for ADPLL RPA (documentation only)
// Not compiled — TopModule is provided by VerilogCoder generated output
//
// module TopModule (clk, reset, fcw, phr, phr_int, phr_frac);
//     reg [31:0] phr_reg;
//     always @(posedge clk)
//         if (reset) phr_reg <= 0;
//         else       phr_reg <= phr_reg + fcw;
//     assign phr      = phr_reg;
//     assign phr_int  = phr_reg[31:24];
//     assign phr_frac = phr_reg[23:0];
// endmodule
